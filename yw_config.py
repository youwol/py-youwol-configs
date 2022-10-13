import asyncio
from pathlib import Path
from typing import Optional

import aiohttp
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.environment.config_from_module import IConfigurationFactory, Configuration
from youwol.configuration.models_config import Events, Redirection, CdnOverride, JwtSource, Projects

import youwol_files_backend as files_backend
from youwol.environment.projects_loader import ProjectLoader
from youwol.environment.utils import auto_detect_projects
from youwol.environment.youwol_environment import YouwolEnvironment
from youwol.pipelines import HelmChartsInstall, K8sClusterTarget, DockerImagesPush, DockerRepo, PackagesPublishYwCdn, \
    YwPlatformTarget
from youwol.pipelines.pipeline_typescript_weback_npm import lib_ts_webpack_template, app_ts_webpack_template, \
    PackagesPublishNpm, PublicNpmRepo
from youwol.routers.custom_commands.models import Command
from youwol_utils import execute_shell_cmd
from youwol_utils import reload_youwol_environment, parse_json
from youwol_utils.admin import clean_visitors, CleanVisitorsBody
from youwol_utils.clients.file_system import LocalFileSystem
from youwol_utils.context import Context
from youwol.main_args import MainArguments

from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol_utils.servers.fast_api import FastApiRouter

youwol_root = Path.home() / 'Projects' / 'youwol-open-source'
secrets_folder: Path = youwol_root / "secrets"
npm_path = youwol_root / "npm"
npm_youwol_path = npm_path / "@youwol"
npm_externals_path = npm_path / "cdn-externals"
cache_dir = youwol_root / 'py-yw-configs' / 'py-youwol-configs' / "youwol_config" / "youwol_system"

async def on_load(ctx: Context):
    await ctx.info("Hello YouWol")


class MyDispatch(AbstractDispatch):

    async def apply(self, incoming_request: Request, call_next: RequestResponseEndpoint,
                    context: Context) -> Optional[Response]:

        if incoming_request.url.path.startswith(
                "/api/assets-gateway/assets/UUhsdmRYZHZiQzl3YkdGMFptOXliUzFsYzNObGJuUnBZV3h6"
        ):
            await context.info(text="MyDispatch", labels=["MyDispatch"])
        return None

    def __str__(self):
        return "My custom dispatch!"


async def publish_pyodide_packages(context: Context):
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False))

    env: YouwolEnvironment = await context.get('env', YouwolEnvironment)
    def get_url_run(action: str):
        return f"http://localhost:{env.httpPort}/admin/projects/{project.id}/flows/prod/steps/{action}/run"

    async with context.start(action="Publish pyodide packages") as ctx:
        projects = await ProjectLoader.get_projects(env=env, context=ctx)
        pyodide_projects = [p for p in projects if "@pyodide" in p.name]
        await ctx.info(text="pyodide projects retrieved", data={"projects": pyodide_projects})

        errors = []
        for project in pyodide_projects:
            async with ctx.start(action=f"Publish pyodide package {project.name}") as ctx_project:

                auth_token = await env.get_auth_token(context=ctx_project, remote_host=env.selectedRemote)
                headers = {"Authorization": f"Bearer {auth_token}"}
                async with await session.post(url=get_url_run('build'), headers=headers) as resp:
                    if resp.status == 200:
                        await ctx_project.info(text="Build successful")
                    else:
                        errors.append(['build', project.name])
                        continue

                async with await session.post(url=get_url_run('cdn-local'), headers=headers) as resp:
                    if resp.status == 200:
                        await ctx_project.info(text="publish local successful")
                    else:
                        errors.append(['build', project.name])
        if errors:
            await context.error(text="Errors occurred", data={"errors": errors})


async def get_files_backend_router(ctx: Context):
    env: YouwolEnvironment = await ctx.get('env', YouwolEnvironment)
    root_path = env.pathsBook.local_storage / files_backend.Constants.namespace / 'youwol-users'
    config = files_backend.Configuration(
        file_system=LocalFileSystem(root_path=root_path)
    )
    return files_backend.get_router(config)


async def start_backend(body, ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    path = Path.home() / "Projects" / "youwol-open-source" / "python" / body['name'] / 'src' / 'main.py'
    from subprocess import Popen
    Popen(["python", path, body['conf'], str(env.httpPort)])

    async def refresh_env():
        await asyncio.sleep(1)
        await reload_youwol_environment(port=env.httpPort)
    asyncio.create_task(refresh_env())
    return {}


async def git_db_backup(body, ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    repo_path = env.pathsBook.databases

    return_code, outputs = await execute_shell_cmd(
        cmd=f"(cd {repo_path} && git config --get remote.origin.url)",
        context=ctx
    )
    await ctx.info(f"Repo url: {outputs[0]}")
    message = body["message"] if "message" in body else "Backup"

    return_code, outputs = await execute_shell_cmd(
        cmd=f'(cd {repo_path} && git add -A && git commit -m "{message}" && git push)',
        context=ctx
    )
    if return_code != 0:
        raise RuntimeError("Error while pushing in repo")
    return {
        "status": "backup synchronized",
        "commitMessage": message
    }


async def cmd_clean_visitors(context: Context):
    async with context.start("Execute clean visitors command") as ctx:  # type: Context
        env: YouwolEnvironment = await ctx.get('env', YouwolEnvironment)
        conf = parse_json(env.pathsBook.secrets)['cleanVisitorsOidcConfig']
        await ctx.info(text="oidc config", data=conf)
        await clean_visitors(body=CleanVisitorsBody(**conf), context=ctx)
        return {
            "status": "OK"
        }


class ConfigurationFactory(IConfigurationFactory):

    portsBookBacks = {
        "stories-backend": 4001,
        "cdn-backend": 4002,
        "assets-gateway": 4003,
        "cdn-apps-server": 4004,
        "tree-db-backend": 4005,
        "assets-backend": 4006,
        "flux-backend": 4007,
        "cdn-sessions-storage": 4008,
        "files-backend": 4009
    }
    portsBookFronts = {
        "@youwol/developer-portal": 3000,
        "@youwol/stories": 3001,
        "@youwol/exhibition-halls": 3002,
        "@youwol/dashboard-infrastructure": 3003,
        "@youwol/platform": 3004,
        "@youwol/flux-builder": 3005,
        "@youwol/dashboard-developer": 3006,
        "@youwol/network": 3007,
        "@youwol/explorer": 3008,
        "@youwol/workspace-explorer": 3009,
        "@youwol/cdn-explorer": 3010,
        "@youwol/flux-runner": 3011,
        "@youwol/python-playground": 3012,
        "@youwol/todo-app-js": 4000,
    }

    async def get(self,  main_args: MainArguments) -> Configuration:

        return Configuration(
            openIdHost="platform.youwol.com",
            platformHost="platform.youwol.com",
            jwtSource=JwtSource.CONFIG,
            dataDir=youwol_root / 'greinisch-youwol-db',
            cacheDir=cache_dir,
            projects=Projects(
                finder=lambda env, _ctx: auto_detect_projects(
                    env=env,
                    root_folder=youwol_root,
                    ignore=["**/dist", "**/py-youwol", "**/@youwol/cdn-client/src/tests"]
                ),
                templates=[
                    lib_ts_webpack_template(folder=npm_youwol_path / 'auto-generated'),
                    app_ts_webpack_template(folder=npm_youwol_path / 'auto-generated')
                ],
                uploadTargets=[
                    HelmChartsInstall(
                        k8sConfigFile=Path.home() / '.kube' / 'config',
                        targets=[
                            K8sClusterTarget(
                                name='dev',
                                context="context-dev"
                            ),
                            K8sClusterTarget(
                                name='prod',
                                context="context-prod"
                            )
                        ]
                    ),
                    DockerImagesPush(
                        targets=[
                            DockerRepo(
                                name="gitlab-docker-repo",
                                host="registry.gitlab.com/youwol/platform"
                            )
                        ]
                    ),
                    PackagesPublishYwCdn(
                        targets=[
                            YwPlatformTarget(
                                name="dev",
                                host="platform.dev.youwol.com"
                            ),
                            YwPlatformTarget(
                                name="prod",
                                host="platform.youwol.com"
                            ),
                        ]
                    ),
                    PackagesPublishNpm(
                        targets=[
                            PublicNpmRepo(
                                name="public"
                            )
                        ]
                    )
                ]
            ),
            portsBook={**self.portsBookFronts, **self.portsBookBacks},
            routers=[
                FastApiRouter(base_path='/api/files-backend', router=get_files_backend_router)
            ],
            dispatches=[
                *[Redirection(from_url_path=f'/api/{name}', to_url=f'http://localhost:{port}')
                  for name, port in self.portsBookBacks.items()],
                *[CdnOverride(packageName=name, port=port)
                  for name, port in self.portsBookFronts.items()],
                MyDispatch()
            ],
            events=Events(
                onLoad=lambda config, ctx: on_load(ctx)
            ),
            customCommands=[
                Command(
                    name="start-backend",
                    do_post=lambda body, ctx: start_backend(body, ctx)
                ),
                Command(
                    name="git-db-backup",
                    do_post=lambda body, ctx: git_db_backup(body, ctx)
                ),
                Command(
                    name="clean-visitors (prod)",
                    do_post=lambda _body, ctx: cmd_clean_visitors(ctx)
                ),
                Command(
                    name="publish pyodide packages",
                    do_post=lambda _body, ctx: publish_pyodide_packages(ctx)
                )
            ]
        )
