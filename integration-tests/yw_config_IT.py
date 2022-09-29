import asyncio
import json
import os
import shutil
from pathlib import Path
import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

import youwol_files_backend as files_backend
from youwol.configuration.config_from_module import IConfigurationFactory, Configuration
from youwol.configuration.models_config import Redirection, CdnOverride, JwtSource
from youwol.environment.clients import RemoteClients
from youwol.environment.youwol_environment import YouwolEnvironment
from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol.routers.custom_commands.models import Command

from youwol.utils.utils_low_level import execute_shell_cmd, sed_inplace
from youwol_utils import decode_id
from youwol_utils.clients.file_system import LocalFileSystem
from youwol_utils.context import Context
from youwol.main_args import MainArguments
from youwol_utils.request_info_factory import url_match
from youwol_utils.utils_paths import parse_json


async def clone_project(git_url: str, new_project_name: str, ctx: Context):

    folder_name = new_project_name.split("/")[-1]
    env = await ctx.get('env', YouwolEnvironment)
    parent_folder = env.pathsBook.config.parent / 'projects'
    dst_folder = parent_folder / folder_name
    await execute_shell_cmd(cmd=f"(cd {parent_folder} && git clone {git_url})",
                            context=ctx)
    os.rename(parent_folder / git_url.split('/')[-1].split('.')[0], parent_folder / folder_name)
    old_project_name = parse_json(dst_folder / 'package.json')['name']
    sed_inplace(dst_folder / 'package.json', old_project_name, new_project_name)
    sed_inplace(dst_folder / 'index.html', old_project_name, new_project_name)
    return {}


async def purge_downloads(ctx: Context):

    env = await ctx.get('env', YouwolEnvironment)
    host = env.selectedRemote
    assets_gtw = await RemoteClients.get_assets_gateway_client(remote_host=host, context=ctx)
    env: YouwolEnvironment = await ctx.get('env', YouwolEnvironment)
    default_drive = await env.get_default_drive(context=ctx)
    resp = await assets_gtw.get_tree_folder_children(default_drive.downloadFolderId)
    await asyncio.gather(
        *[assets_gtw.delete_tree_item(item["treeId"]) for item in resp["items"]],
        *[assets_gtw.delete_tree_folder(item["folderId"]) for item in resp["folders"]]
    )
    await assets_gtw.purge_drive(default_drive.driveId)
    return {}


async def empty_buckets_minio():
    from minio import Minio
    """
    to start minio:
    from environment/minio:
    sudo chown -R greinisch ./data && sudo chmod u+rxw ./data
    ./minio server ./data
    """
    minio = Minio(
        endpoint="127.0.0.1:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False
    )
    buckets = minio.list_buckets()
    for bucket in buckets:
        objects = minio.list_objects(bucket_name=bucket.name, recursive=True)
        for obj in objects:
            minio.remove_object(bucket_name=bucket.name, object_name=obj.object_name)


minio_used = False


async def use_minio():
    global minio_used
    minio_used = True


async def reset(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    env.reset_cache()
    if minio_used:
        await empty_buckets_minio()

    parent_folder = env.pathsBook.config.parent
    shutil.rmtree(parent_folder / "databases", ignore_errors=True)
    shutil.rmtree(parent_folder / "projects", ignore_errors=True)
    shutil.rmtree(parent_folder / "youwol_system", ignore_errors=True)
    os.mkdir(parent_folder / "projects")
    shutil.copytree(src=parent_folder / "empty_databases",
                    dst=parent_folder / "databases")


async def create_remote_folder(body, ctx):

    env = await ctx.get('env', YouwolEnvironment)
    host = env.selectedRemote
    assets_gtw = await RemoteClients.get_assets_gateway_client(remote_host=host, context=ctx)
    await assets_gtw.create_folder(parent_folder_id=body['parentFolderId'], body=body)


async def test_command_post(body, context: Context):

    await context.info(text="test message", data={"body": body})
    return body["returnObject"]


async def create_test_data_remote(context: Context):
    async with context.start("create_new_story_remote") as ctx:
        env = await context.get('env', YouwolEnvironment)
        host = env.selectedRemote
        await ctx.info(f"selected Host for creation: {host}")
        gtw = await RemoteClients.get_assets_gateway_client(remote_host=host, context=ctx)

        resp_stories = await gtw.get_stories_backend_router().create_story(body={
            "storyId": "504039f7-a51f-403d-9672-577b846fdbd8",
            "title": "New story (remote test data in http-clients)"
        }, params=[('folder-id', 'private_51c42384-3582-494f-8c56-7405b01646ad_default-drive_home')])

        resp_flux = await gtw.get_flux_backend_router().create_project(body={
            "projectId": "2d5cafa9-f903-4fa7-b343-b49dfba20023",
            "description": 'a flux project dedicated to test in http-clients',
            "name": "New flux-project (remote test data in http-clients)"
        }, params=[('folder-id', 'private_51c42384-3582-494f-8c56-7405b01646ad_default-drive_home')])

        content = json.dumps({'description': 'a file uploaded in remote env for test purposes (http-clients)'})
        form = {
            'file': str.encode(content),
            'content_type': 'application/json',
            'file_id': "f72290f2-90bc-4192-80ca-20f983a1213d",
            'file_name': "Uploaded file (remote test data in http-clients)"
        }
        resp_data = await gtw.get_files_backend_router().upload(
            data=form,
            params=[('folder-id', 'private_51c42384-3582-494f-8c56-7405b01646ad_default-drive_home')]
        )
        resp = {
            "respStories": resp_stories,
            "respFlux": resp_flux,
            "respData": resp_data
        }
        await ctx.info(f"Story successfully created", data=resp)
        return resp


class BrotliDecompress(AbstractDispatch):

    async def apply(self, incoming_request: Request, call_next: RequestResponseEndpoint, context: Context):

        match_cdn, params = url_match(incoming_request, "GET:/api/assets-gateway/raw/package/*/**")
        env = await context.get('env', YouwolEnvironment)
        if match_cdn and len(params) > 0 and decode_id(params[0]) in env.portsBook:
            return None

        match_files, _ = url_match(incoming_request, "GET:/api/assets-gateway/files-backend/files/*")
        if match_cdn or match_files:
            response = await call_next(incoming_request)
            if response.headers.get('content-encoding') != 'br':
                return response

            await context.info("Apply brotli decompression")
            binary = b''
            # noinspection PyUnresolvedReferences
            async for data in response.body_iterator:
                binary += data
            headers = {k: v for k, v in response.headers.items()
                       if k not in ['content-length', 'content-encoding']}
            decompressed = brotli.decompress(binary)
            resp = Response(decompressed.decode('utf8'), headers=headers)
            return resp

        return None

    def __str__(self):
        return "Decompress brotli on te fly because in jest brotli is not supported"


async def get_files_backend_config(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    root_path = env.pathsBook.local_storage / files_backend.Constants.namespace / 'youwol-users'
    config = files_backend.Configuration(
        file_system=LocalFileSystem(root_path=root_path)
    )
    return files_backend.get_router(config)


class ConfigurationFactory(IConfigurationFactory):
    portsBookFronts = {
        #"@youwol/developer-portal": 3000,
        #"@youwol/stories": 3001,
    }
    portsBookBacks = {
        #"cdn-backend": 4002,
    }

    async def get(self, main_args: MainArguments) -> Configuration:
        return Configuration(
            openIdHost="platform.youwol.com",
            platformHost="platform.youwol.com",
            jwtSource=JwtSource.CONFIG,
            httpPort=2001,
            dataDir=Path(__file__).parent / 'databases',
            cacheDir=Path(__file__).parent / 'youwol_system',
            projectsDirs=[Path(__file__).parent / 'projects'],
            dispatches=[
                BrotliDecompress(),
                *[Redirection(from_url_path=f'/api/{name}', to_url=f'http://localhost:{port}')
                  for name, port in self.portsBookBacks.items()],
                *[CdnOverride(packageName=name, port=port)
                  for name, port in self.portsBookFronts.items()],
            ],
            routers=[
                # FastApiRouter(base_path='/api/files-backend', router=get_files_backend_config)
            ],
            portsBook={**self.portsBookFronts, **self.portsBookBacks},
            customCommands=[
                Command(
                    name="use-minio",
                    do_get=lambda ctx: use_minio()
                ),
                Command(
                    name="reset",
                    do_get=lambda ctx: reset(ctx)
                ),
                Command(
                    name="clone-project",
                    do_post=lambda body, ctx: clone_project(body['url'], body['name'], ctx)
                ),
                Command(
                    name="purge-downloads",
                    do_delete=lambda ctx: purge_downloads(ctx)
                ),
                Command(
                    name="create-remote-folder",
                    do_post=lambda body, ctx: create_remote_folder(body, ctx)
                ),
                Command(
                    name="test-cmd-post",
                    do_post=lambda body, ctx: test_command_post(body, ctx)
                ),
                Command(
                    name="test-cmd-put",
                    do_put=lambda body, ctx: body["returnObject"]
                ),
                Command(
                    name="test-cmd-delete",
                    do_delete=lambda ctx: {"status": "deleted"}
                ),
                Command(
                    name="create-test-data-remote",
                    do_get=lambda ctx: create_test_data_remote(ctx)
                )
            ],
        ).extending_profile(
            name='profile-1',
            conf=Configuration()
        )
