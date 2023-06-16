from pathlib import Path

from youwol.app.environment import (
    Configuration,
    System,
    CloudEnvironments,
    LocalEnvironment,
    Connection,
    CloudEnvironment,
    get_standard_auth_provider,
    BrowserAuth,
)

browser_auth = BrowserAuth(authId="browser")

environments = [
    CloudEnvironment(
        envId="dev" if "dev" in host else "prod",
        host=host,
        authProvider=get_standard_auth_provider(host),
        authentications=[browser_auth],
    )
    for host in ["platform.youwol.com", "platform.dev.youwol.com"]
]


Configuration(
    system=System(
        httpPort=2000,
        cloudEnvironments=CloudEnvironments(
            defaultConnection=Connection(envId="prod", authId="browser"),
            environments=environments,
        ),
        localEnvironment=LocalEnvironment(
            dataDir=Path(__file__).parent / "db",
            cacheDir="./youwol-system",
        ),
    )
)
