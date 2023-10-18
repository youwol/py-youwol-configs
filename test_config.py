"""
This configuration is commonly used for integration testing of npm packages along with py-youwol environment.
It connects to the 'integration' environment of YouWol when needed.
"""
import os
import shutil
from pathlib import Path

import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from youwol.app.environment import (
    CloudEnvironment,
    CloudEnvironments,
    Command,
    Configuration,
    Connection,
    CustomEndPoints,
    Customization,
    CustomMiddleware,
    DirectAuth,
    IConfigurationFactory,
    LocalEnvironment,
    System,
    TokensStorageInMemory,
    YouwolEnvironment, get_standard_auth_provider,
)
from youwol.app.main_args import MainArguments
from youwol.app.routers.projects import ProjectLoader

from youwol.utils.context import Context, Label

users = [
    (os.getenv("USERNAME_INTEGRATION_TESTS"), os.getenv("PASSWORD_INTEGRATION_TESTS")),
    (
        os.getenv("USERNAME_INTEGRATION_TESTS_BIS"),
        os.getenv("PASSWORD_INTEGRATION_TESTS_BIS"),
    ),
]

direct_auths = [
    DirectAuth(authId=email, userName=email, password=pwd) for email, pwd in users
]

cloud_env = CloudEnvironment(
    envId="integration",
    host="platform.int.youwol.com",
    authProvider=get_standard_auth_provider("platform.int.youwol.com"),
    authentications=direct_auths,
)


async def reset(ctx: Context):
    env: YouwolEnvironment = await ctx.get("env", YouwolEnvironment)
    env.reset_cache()
    env.reset_databases()
    parent_folder = env.pathsBook.config.parent
    shutil.rmtree(parent_folder / "projects", ignore_errors=True)
    shutil.rmtree(parent_folder / "youwol_system", ignore_errors=True)
    os.mkdir(parent_folder / "projects")
    await ProjectLoader.initialize(env=env)


class BrotliDecompressMiddleware(CustomMiddleware):
    async def dispatch(
            self,
            incoming_request: Request,
            call_next: RequestResponseEndpoint,
            context: Context,
    ):
        async with context.start(
                action="BrotliDecompressMiddleware.dispatch", with_labels=[Label.MIDDLEWARE]
        ) as ctx:  # type: Context
            response = await call_next(incoming_request)
            if response.headers.get("content-encoding") != "br":
                return response
            await ctx.info(
                text="Got 'br' content-encoding => apply brotli decompression"
            )
            await context.info("Apply brotli decompression")
            binary = b""
            # noinspection PyUnresolvedReferences
            async for data in response.body_iterator:
                binary += data
            headers = {
                k: v
                for k, v in response.headers.items()
                if k not in ["content-length", "content-encoding"]
            }
            decompressed = brotli.decompress(binary)
            resp = Response(decompressed.decode("utf8"), headers=headers)
            return resp


class ConfigurationFactory(IConfigurationFactory):
    async def get(self, _main_args: MainArguments) -> Configuration:
        return Configuration(
            system=System(
                httpPort=2001,
                tokensStorage=TokensStorageInMemory(),
                cloudEnvironments=CloudEnvironments(
                    defaultConnection=Connection(
                        envId="integration",
                        authId=direct_auths[0].authId
                    ),
                    environments=[cloud_env],
                ),
                localEnvironment=LocalEnvironment(
                    dataDir=Path(__file__).parent / "databases",
                    cacheDir=Path(__file__).parent / "youwol_system",
                ),
            ),
            customization=Customization(
                middlewares=[
                    BrotliDecompressMiddleware(),
                ],
                endPoints=CustomEndPoints(
                    commands=[
                        Command(name="reset", do_get=reset),
                    ]
                ),
            ),
        )