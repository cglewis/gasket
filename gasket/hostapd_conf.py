"""Configuration for a hostapd server."""

from gasket.gasket_conf_utils import validate_ip_address
from gasket.gasket_conf_utils import validate_port
from gasket.gasket_conf_utils import get_log_level

from gasket import gasket_conf


class HostapdConf(gasket_conf.GasketConf):
    """Stores state related to a hostapd instance.
    """

    request_sock = None
    unsolicited_sock = None
    udp = False

    name = None
    description = None
    remote_host = None
    remote_port = None
    unix_socket_path = None
    unsolicited_bind_address = None
    request_bind_address = None
    request_bind_port = None
    unsolicited_bind_port = None
    request_timeout = None
    unsolicited_timeout = None
    ifname = None
    logger_level = None

    ports = None

    defaults = {
        'name': None,
        'description': None,
        'unix_socket_path': None,
        'remote_host': None,
        'remote_port': None,
        'unsolicited_bind_address': None,
        'request_bind_address': None,
        'request_bind_port': None,
        'unsolicited_bind_port': None,
        'request_timeout': 5,
        'unsolicited_timeout': 5,
        'ifname': None,
        'logger_level': None,
    }

    defaults_types = {
        'name': str,
        'description': str,
        'unix_socket_path': str,
        'remote_host': str,
        'remote_port': int,
        'unsolicited_bind_address': str,
        'request_bind_address': str,
        'request_bind_port': int,
        'unsolicited_bind_port': int,
        'request_timeout': int,
        'unsolicited_timeout': int,
        'ifname': str,
        'logger_level': (str, int),
    }
 
    def __init__(self, _id, conf):
        super(HostapdConf, self).__init__(_id, conf)
        self.ports = {}

    def check_config(self):
        super(HostapdConf, self).check_config()
        if self.unix_socket_path:
            self.udp = False
            assert self.remote_host is None and self.remote_port is None
        else:
            self.udp = True
            validate_port(self.remote_port)
            validate_ip_address(self.remote_host)

        if self.request_bind_address:
            validate_ip_address(self.request_bind_address)
        if self.request_bind_port:
            validate_port(self.request_bind_port)
        if self.unsolicited_bind_address:
            validate_ip_address(self.unsolicited_bind_address)
        if self.unsolicited_bind_port:
            validate_port(self.unsolicited_bind_port)

        self.logger_level = get_log_level(self.logger_level)

    def set_defaults(self):
        super(HostapdConf, self).set_defaults()
        self._set_default('name', self._id)
        self._set_default('description', self.name)

    def add_port(self, port):
        """add port that is managed by this hostapd.
        Args:
            port (Port):
        """
        self.ports[port.number] = port
