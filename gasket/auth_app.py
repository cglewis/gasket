"""This is the controller side authentication app.
It communicates with an authentication server (hostapd, captive portal) via HTTP.
And with rule_manager which communicates with Faucet via changing the Faucet configuration file,
and sending it a SIGHUP.
"""
# pylint: disable=import-error

import argparse
import queue
import re
import signal
import sys

from gasket.auth_config import AuthConfig
from gasket import auth_app_utils
from gasket import config_parser
from gasket import hostapd_socket_thread
from gasket import rabbitmq
from gasket import rule_manager
from gasket import work_item
from gasket.host import UnlearntUnauthenticatedHost


class Proto(object):
    """Class for protocol constants.
    """
    ETHER_ARP = 0x0806
    ETHER_IPv4 = 0x0800
    ETHER_IPv6 = 0x86DD
    ETHER_EAPOL = 0x888E
    IP_TCP = 6
    IP_UDP = 17
    DHCP_CLIENT_PORT = 68
    DHCP_SERVER_PORT = 67
    DNS_PORT = 53
    HTTP_PORT = 80


LEARNED_MACS_REGEX = r"""learned_macs{dp_id="(0x[a-f0-9]+)",dp_name="([\w-]+)",n="(\d+)",port="(\d+)",vlan="(\d+)"}"""


class AuthApp(object):
    '''
    This class recieves messages hostapd_ctrl from the portal via
    UNIX DOMAIN sockets, about the a change of state of the users.
    This could be either a log on or a log off of a user.
    The information is then passed on to rule_manager which
    installs/removes any appropriate rules.
    '''


    config = None
    rule_man = None
    logger = None
    logname = 'auth_app'

    work_queue = None
    threads = []

    dps = {}
    # dp_name : Datapath
    macs = {}
    # mac : Host
    hostapds = {}
    # hostapd_name : HostapdConf

    def __init__(self, config, logger):
        super(AuthApp, self).__init__()
        self.config = config

        # TODO replace the AuthConfig with the faucet conf class style.
        # this is just hack until it is all complete.
        temp_config = {}
        temp_config['hostapds'] = config.hostapds
        temp_config['dps'] = config.dps
        self.dps, self.hostapds = config_parser.parse_config(temp_config)

        self.logger = logger
        self.rule_man = rule_manager.RuleManager(self.config, self.logger)
        self.learned_macs_compiled_regex = re.compile(LEARNED_MACS_REGEX)
        self.work_queue = queue.Queue()

    def start(self):
        """Starts separate thread for each hostapd socket.
        And runs as the worker thread processing the (de)authentications/.

        Main Worker thread.
        """
        signal.signal(signal.SIGINT, self._handle_sigint)

        self.logger.info('Starting hostapd socket threads')
        print('Starting hostapd socket threads ...')

        for hostapd_conf in self.hostapds.values():
            hst = hostapd_socket_thread.HostapdSocketThread(hostapd_conf, self.work_queue,
                                                            self.config.logger_location)
            self.logger.info('Starting thread %s', hst)
            hst.start()
            self.threads.append(hst)
            self.logger.info('Thread running')

        rt = rabbitmq.RabbitMQ(self.work_queue, self.config.logger_location)
        try:
            rt.start()
            self.threads.append(rt)
        except Exception as e:
            self.logger.exception(e)

        self.get_prometheus_mac_learning()
        print('Started socket Threads.')
        print('Working')
        self.logger.info('Working worker thread.')
        while True:
            work = self.work_queue.get()
            try:
                self.logger.info('Got %s work from queue ', type(work))
                if isinstance(work, work_item.AuthWorkItem):
                    self.authenticate(work.mac, work.username, work.acllist, work.hostapd_name)
                elif isinstance(work, work_item.DeauthWorkItem):
                    self.deauthenticate(work.mac, work.hostapd_name)
                elif isinstance(work, work_item.L2LearnWorkItem):
                    self.l2learn(work)
                elif isinstance(work, work_item.PortChangeWorkItem):
                    self.port_status_handler(work)
                else:
                    self.logger.warn("Unsupported WorkItem type: %s", type(work))
            except Exception as e:
                self.logger.exception(e)

    def l2learn(self, host_wi):
        """Learns a host, if host is already authenticated rules are applied.
        Args:
            host_wi (work_item.L2LearnWorkItem): the host to learn
        """
        dp_name = host_wi.dp_name
        mac = host_wi.mac
        ip = host_wi.ip
        port_no = host_wi.port
        self.logger.info('learning mac %s at dp: %s port: %d', mac, dp_name, port_no)
        if not mac in self.macs:
            self.logger.info('learning new host %s', mac)
            self.macs[mac] = UnlearntUnauthenticatedHost(mac=mac, ip=ip,
                                                         logger=self.logger, rule_man=self.rule_man)

        self.macs[mac] = self.macs[mac].learn(self.dps[dp_name].ports[port_no])

    def get_prometheus_mac_learning(self):
        """Queries the prometheus faucet client,
        And creates L2Learn work for macs already learnt.
        """
        # query faucets promethues.
        self.logger.info('querying prometheus for "learned_macs"')
        try:
            prom_mac_table = auth_app_utils.scrape_prometheus_vars(self.config.prom_url,
                                                                   ['learned_macs'])[0]
        except Exception as e:
            self.logger.exception(e)
            return
        self.logger.debug('queried prometheus. mac_table:\n%s\n',
                          prom_mac_table)

        for line in prom_mac_table:
            labels, float_as_mac = line.split(' ')
            macstr = auth_app_utils.float_to_mac(float_as_mac)
            self.logger.debug('float %s is mac %s', float_as_mac, macstr)

            # if this is also an access port, we have found the dpid and the port
            values = self.learned_macs_compiled_regex.match(labels)
            dpid, dp_name, n, port, vlan = values.groups()
            self.work_queue.put(work_item.L2LearnWorkItem(dp_name, int(dpid, 16), int(port),
                                                          int(vlan), macstr, None))

    def authenticate(self, mac, user, acl_list, hostapd_name):
        """Authenticates the user as specifed by adding ACL rules
        to the Faucet configuration file. Once added Faucet is signaled via SIGHUP.
        Args:
            mac (str): MAC Address.
            user (str): Username.
            acl_list (list of str): names of acls (in order of highest priority to lowest) to be applied.
            hostapd_name (str): name of the hostapd that did the auth.
        """
        self.logger.info("authenticating: %s %s", mac, user)
        if not mac in self.macs:
            self.macs[mac] = UnlearntUnauthenticatedHost(mac=mac, logger=self.logger,
                                                         rule_man=self.rule_man)

        host = self.macs[mac]
        port = host.get_authing_learn_ports()
        hapd = self.hostapds[hostapd_name]

        # if only one port, must be located on that port.
        # otherwise we use the last learnt auth port
        if len(hapd.ports) == 1:
            port = next(iter(hapd.ports.values()))
            host = self.macs[mac].learn(port)

        host = host.authenticate(user, port, acl_list)
        self.macs[mac] = host
        self.logger.info('authenticate complete')
        # TODO probably shouldn't return success if the switch/port cannot be found.
        # but at this stage auth server (hostapd) can't do anything about it.
        # Perhaps look into the CoA radius thing, so that process looks like:
        #   - client 1x success, send to here.
        #   - can't find switch. return failure.
        #   - hostapd revokes auth, so now client is aware there was an error.
#        if not success:
            # TODO one or the other?
#            self.hapd_req.deauthenticate(mac)
#            self.hapd_req.disassociate(mac)

    def deauthenticate(self, mac, hostapd_name, username=None):
        """Deauthenticates the mac and username by removing related acl rules
        from Faucet's config file.
        Args:
            mac (str): mac address string to deauth
            username (str): username to deauth.
            hostapd_name (str): name of the hostapd that did the deauth.
        """
        self.logger.info('deauthenticating: %s %s', mac, username)
        host = self.macs.get(mac, None)
        if host:
            self.macs[mac] = host.deauthenticate(None)
        self.logger.info('deauthenticate complete')
        # TODO possibly handle success somehow. However the client wpa_supplicant, etc,
        # will likley think it has logged off, so is there anything we can do from hostapd to
        # say they have not actually logged off.
        # EAP LOGOFF is a one way message (not ack-ed)

    def port_status_handler(self, port_change):
        """Deauthenticates all hosts on a port if the port has gone down.
        """
        dpid = port_change.dp_id
        port_no = port_change.port_no
        port_status = port_change.status
        dp_name = port_change.dp_name
        self.logger.info('DPID %d, Port %s has changed status: %d', dpid, port_no, port_status)
        if not port_status: # port is down
            port = self.dps[dp_name].ports[port_no]
            if port.auth_mode == 'access':
                self.logger.debug('DP %s is mananged.', dp_name)
                for mac in list(port.authed_hosts):
                    self.logger.debug('mac: %s deauthed via port down' % mac)
                    self.macs[mac] = self.macs[mac].deauthenticate(port)
                self.logger.debug('reset port completed')

    def _handle_sigint(self, sigid, frame):
        """Handles the SIGINT signal.
        Closes the hostapd control interfaces, and kills the main thread ('self.run').
        """
        self.logger.info('SIGINT Received - Killing hostapd socket threads ...')
        for t in self.threads:
            t.kill()
        self.logger.info('Threads killed')
        sys.exit()


if __name__ == "__main__":
    print('Parsing args ...')
    parser = argparse.ArgumentParser()
    parser.add_argument('config', metavar='config', type=str,
                        nargs=1, help='path to configuration file')
    args = parser.parse_args()
    config_filename = '/etc/faucet/gasket/auth.yaml'
    if args.config:
        config_filename = args.config[0]
    print('Loading config %s' % config_filename)
    auth_config = AuthConfig(config_filename)
    log = auth_app_utils.get_logger('auth_app', auth_config.logger_location, auth_config.logger_level, 1)

    aa = AuthApp(auth_config, log)
    print('Running AuthApp')
    try:
        aa.start()
    except Exception as e:
        log.exception(e)
