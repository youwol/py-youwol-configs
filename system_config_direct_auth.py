from pathlib import Path

from youwol.app.environment import (
    Configuration,
    System,
    CloudEnvironments,
    LocalEnvironment,
    DirectAuth,
    BrowserAuth,
    CloudEnvironment,
    get_standard_auth_provider,
    Connection,
    get_standard_youwol_env,
)

company_name = "foo"
company_youwol = CloudEnvironment(
    envId=company_name,
    host=f"platform.{company_name}.com",
    authProvider=get_standard_auth_provider(f"platform.{company_name}.com"),
    authentications=[
        BrowserAuth(authId='browser'),
        DirectAuth(authId='bar', userName='bar', password='bar-pwd')
    ]
)


Configuration(
    system=System(
        httpPort=2000,
        cloudEnvironments=CloudEnvironments(
            defaultConnection=Connection(
                envId=company_name,
                authId="bar"
            ),
            environments=[
                get_standard_youwol_env(env_id='public-youwol'),
                company_youwol
            ]
        ),
        localEnvironment=LocalEnvironment(
            dataDir=Path(__file__).parent / 'db',
            cacheDir='./youwol-system',
        )
    )
)
