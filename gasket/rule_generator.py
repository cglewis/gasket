"""Interface to find and create the Faucet ACL rules, form an external source (file, db)
yaml keys "_authport_*, and values "_usermac_" are currently used for replacing with values
as discovered at runtime.
 Switchport (_authport_) that an authenticated user (_usermac_) has authenticated on & with.

TODO maybe make this an interface for yaml or db generator subclasses.
"""
# pytype: disable=pyi-error
import yaml


class RuleGenerator(object):
    """Object for gernerating rules from a yaml file.
    """

    yaml_file = ""
    conf = None
    logger = None

    def __init__(self, rule_file, logger):
        self.reload(rule_file)
        self.logger = logger

    def get_rules(self, username, auth_port_acl, mac, acl_list):
        """Gets Faucet ACL rules for the specified user.
        Replaces placeholder keys/values as required.
        Args:
            username: The username to find rules for.
            auth_port_acl: the port acl name of the port 'username' authenticated on.
            mac: mac address of username's machine
            acl_list (list of str): names of acls (in order of highest priority to lowest) to be applied.
        Returns:
            Dictionary of port_acl names to list of rules.
        """
        # if we don't reload the values that we will want to swap
        # may already be filled if the user has logged on already.

        # what about doing a copy or deepcopy?
        # and only do a full reload when file has actually changed?
        self.reload(self.yaml_file)

        rules = dict()
        for aclname in acl_list:
            if aclname in list(self.conf['acls']):
                for portacl in list(self.conf['acls'][aclname].keys()):
                    if portacl not in rules:
                        rules[portacl] = []
                    for obj in self.conf['acls'][aclname][portacl]:
                        if isinstance(obj, dict) and 'rule' in obj:
                            r = obj["rule"]
                            for k, v in list(r.items()):
                                if v == "_user-mac_":
                                    r[k] = mac
                                if v == "_user-name_":
                                    r[k] = username
                            d = dict()
                            d["rule"] = r
                            rules[portacl].append(d)
                        elif isinstance(obj, list):
                            for y in obj:
                                if isinstance(y, dict):
                                    # list of dicts
                                    for _, rule in list(y.items()):
                                        r = rule
                                        for k, v in list(r.items()):
                                            if v == "_user-mac_":
                                                r[k] = mac
                                            if v == "_user-name_":
                                                r[k] = username
                                        d = dict()
                                        d["rule"] = r
                                        rules[portacl].append(d)
                                else:
                                    self.logger.warning('list of unrecognised objects')
                                    self.logger.warning('child type: %s' % type(y))
                                    self.logger.warning('list object: %s' % obj)

                        else:
                            self.logger.warning('obj is unrecongnised type %s', type(obj))
                    if portacl == "_authport_":
                        # rename the port acl to the one the user authenticated on.
                        temp = rules[portacl]
                        del rules[portacl]
                        if auth_port_acl in rules:
                            rules[auth_port_acl].extend(temp)
                        else:
                            rules[auth_port_acl] = temp
        return rules

    def reload(self, rule_file):
        """(Re)loads the rule yaml file.
        Args:
            rule_file: path to file.
        """
        self.yaml_file = rule_file
        self.conf = yaml.load(open(rule_file, "r"))

