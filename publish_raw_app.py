
"""
This is about publishing a new 'raw' application in YouWol ecosystem.
Copy/paste your project under the 'projects_root' folder referenced in this file.
In the folder of your project, include a '.yw_pipeline' folder including a 'yw_pipeline.py' file with following content:
```
from youwol.app.environment import YouwolEnvironment
from youwol.app.routers.projects import IPipelineFactory, BrowserApp, Execution, BrowserAppGraphics
from youwol.pipelines.pipeline_raw_app import pipeline, PipelineConfig
from youwol.utils.context import Context


class PipelineFactory(IPipelineFactory):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get(self, _env: YouwolEnvironment, context: Context):
        config = PipelineConfig(target=BrowserApp(
            displayName="My application",
            execution=Execution(
                standalone=True
            ),
            graphics=BrowserAppGraphics(
                appIcon={'class': 'far fa-laugh-beam fa-2x'},
                fileIcon={}
            ),
            links=[
                # E.g. a github link
            ]
        ))
        return await pipeline(config, context)
```
Load (or refresh) the dev. portal application, select your project and proceed to publication.
"""

from pathlib import Path
from youwol.app.environment import (
    Configuration,
    Projects,
    CloudEnvironment,
    get_standard_auth_provider,
    BrowserAuth,
    RecursiveProjectsFinder,
)

from youwol.pipelines import CdnTarget
import youwol.pipelines.pipeline_raw_app as pipeline_raw_app

# Adapt the location of the root folder of the projects you are working on
projects_root = Path.home() / "Projects" / "demos"

# This is to publish in remote environment, here on 'platform.youwol.com', authentication supported by the browser
prod_env = CloudEnvironment(
    envId="prod",
    host="platform.youwol.com",
    authProvider=get_standard_auth_provider("platform.youwol.com"),
    authentications=[BrowserAuth(authId="browser")],
)

pipeline_raw_app.set_environment(
    environment=pipeline_raw_app.Environment(
        cdnTargets=[
            CdnTarget(name="prod", cloudTarget=prod_env, authId="browser"),
        ]
    )
)

Configuration(
    projects=Projects(
        finder=RecursiveProjectsFinder(
            fromPaths=[projects_root],
        ),
    ),
)
