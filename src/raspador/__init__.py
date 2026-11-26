"""raspador: raspagem web compliant sobre o Scrapling."""

__version__ = "0.1.0"

from raspador import adaptive, http, spiders  # noqa: E402
from raspador.adaptive import Selector  # noqa: E402
from raspador.http import async_http_session, delete, get, http_session, post, put  # noqa: E402
from raspador.policy import PolicyError  # noqa: E402
from raspador.robots import RobotsDenied  # noqa: E402
from raspador.spiders import Request, Spider  # noqa: E402

__all__ = [
    "PolicyError",
    "Request",
    "RobotsDenied",
    "Selector",
    "Spider",
    "__version__",
    "adaptive",
    "async_http_session",
    "delete",
    "get",
    "http",
    "http_session",
    "post",
    "put",
    "spiders",
]
