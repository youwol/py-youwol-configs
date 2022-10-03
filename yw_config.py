import asyncio
from pathlib import Path
from typing import Optional

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.configuration.config_from_module import IConfigurationFactory, Configuration
from youwol.configuration.models_config import Events, Redirection, CdnOverride, JwtSource, PipelinesSourceInfo

from youwol.environment.forward_declaration import YouwolEnvironment
import youwol_files_backend as files_backend
from youwol.pipelines import HelmChartsInstall, K8sClusterTarget, DockerImagesPush, DockerRepo, PackagesPublishYwCdn, \
    YwPlatformTarget
from youwol.pipelines.pipeline_typescript_weback_npm import lib_ts_webpack_template, app_ts_webpack_template, \
    PackagesPublishNpm, PublicNpmRepo
from youwol.routers.custom_commands.models import Command
from youwol.utils.utils_low_level import execute_shell_cmd
from youwol_utils import reload_youwol_environment, parse_json
from youwol_utils.admin import clean_visitors, CleanVisitorsBody
from youwol_utils.clients.file_system import LocalFileSystem
from youwol_utils.context import Context
from youwol.main_args import MainArguments

from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol_utils.servers.fast_api import FastApiRouter
from youwol_utils.utils_paths import FileListing, matching_files

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


async def get_files_backend_router(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
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


def auto_detect_projects():
    file_listing = FileListing(
        include=["**/yw_pipeline.py"],
        ignore=["**/node_modules", "**/.template", "**/.git", "**/dist", str(cache_dir / '**'), '**/py-youwol'])
    yw_pipelines = matching_files(youwol_root, file_listing)
    return [p.parent.parent for p in yw_pipelines]


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

        projects = auto_detect_projects()
        print(f"Auto detection of {len(projects)} projects")

        return Configuration(
            openIdHost="platform.youwol.com",
            platformHost="platform.youwol.com",
            jwtSource=JwtSource.COOKIE,
            dataDir=Path.home() / 'Projects' / 'drive-shared',
            cacheDir=cache_dir,
            projectsDirs=projects,
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
            pipelinesSourceInfo=PipelinesSourceInfo(
                projectTemplates=[
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
                )
            ]
        )
