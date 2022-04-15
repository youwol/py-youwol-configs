import os
from pathlib import Path
from typing import Optional

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.configuration.config_from_module import IConfigurationFactory, Configuration
from youwol.configuration.models_config import Events, Redirection, CdnOverride, K8sCluster
from youwol.configuration.models_k8s import OpenIdConnect, Docker, DockerRepo
from youwol.environment.forward_declaration import YouwolEnvironment
import youwol_files_backend as files_backend
from youwol_utils.clients.file_system import LocalFileSystem
from youwol_utils.context import Context
from youwol.main_args import MainArguments

from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol_utils.servers.fast_api import FastApiRouter

open_source_path = Path.home() / 'Projects' / 'youwol-open-source'
platform_path = Path.home() / 'Projects' / 'platform'
secrets_folder: Path = platform_path / "secrets" / "gc"
from_scratch_conf_folder = open_source_path / 'py-youwol-configs' / "empty_db_config"
npm_youwol_path = open_source_path / "npm" / "@youwol"


def set_py_youwol_env_var():
    os.environ["PY_YOUWOL_SRC"] = str(open_source_path / 'python' / 'py-youwol')
    print(f"Env. variable PY_YOUWOL_SRC set: {os.environ['PY_YOUWOL_SRC']}")


class MyDispatch(AbstractDispatch):

    async def apply(self, incoming_request: Request, call_next: RequestResponseEndpoint,
                    context: Context) -> Optional[Response]:

        if incoming_request.url.path.startswith(
                "/api/assets-gateway/assets/UUhsdmRYZHZiQzl3YkdGMFptOXliUzFsYzNObGJuUnBZV3h6"
        ):
            print("Hey this is my Custom dispatch")
        return None

    def __str__(self):
        return "My custom dispatch!"


async def get_files_backend_config(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    root_path = env.pathsBook.local_storage / files_backend.Constants.namespace / 'youwol-users'
    config = files_backend.Configuration(
        file_system=LocalFileSystem(root_path=root_path)
    )
    return files_backend.get_router(config)


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
        "@youwol/flux-runner": 3011,
        "@youwol/todo-app-js": 4000,
    }

    def __init__(self):
        # some initialization
        pass

    async def get(self,  main_args: MainArguments) -> Configuration:

        return Configuration(
            dataDir=Path.home() / 'Projects' / 'drive-shared',
            cacheDir=open_source_path / 'py-youwol-configs' / "youwol_config" / "youwol_system",
            projectsDirs=[
                npm_youwol_path,
                npm_youwol_path / 'sample-apps',
                npm_youwol_path / '..' / 'cdn-externals' / 'grapes',
                npm_youwol_path / '..' / 'cdn-externals' / 'pyodide',
                npm_youwol_path / '..' / 'cdn-externals' / 'typescript',
                npm_youwol_path / '..' / 'cdn-externals' / 'codemirror',
                npm_youwol_path / 'flux',
                npm_youwol_path / 'flux' / 'flux-view',
                npm_youwol_path / 'grapes-plugins',
                open_source_path / "python",
                open_source_path / "python" / "py-youwol"
            ],
            portsBook={**self.portsBookFronts, **self.portsBookBacks},
            routers=[
                FastApiRouter(base_path='/api/files-backend', router=get_files_backend_config)
            ],
            dispatches=[
                *[Redirection(from_url_path=f'/api/{name}', to_url=f'http://localhost:{port}')
                  for name, port in self.portsBookBacks.items()],
                *[CdnOverride(packageName=name, port=port)
                  for name, port in self.portsBookFronts.items()],
                MyDispatch()
            ],
            k8sCluster=K8sCluster(
                configFile=Path.home() / '.kube' / 'config',
                contextName="gke_thematic-grove-252706_europe-west1_gc-tricot",
                proxyPort=8001,
                host="gc.platform.youwol.com",
                openIdConnect=OpenIdConnect(
                    host="gc.auth.youwol.com",
                    authSecret=secrets_folder / "keycloak" / "youwol-auth.yaml"
                ),
                docker=Docker(
                    repositories=[
                        DockerRepo(
                            name="gitlab-docker-repo",
                            pullSecret=secrets_folder / "gitlab" / "gitlab-docker.yaml",
                            imageUrlBuilder=lambda project, ctx: f"registry.gitlab.com/youwol/platform/{project.name}"
                        )
                    ]
                )
            ),
            events=Events(
                onLoad=lambda config, ctx: set_py_youwol_env_var()
            )
        )
