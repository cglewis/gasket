rm -rf /tmp/faucet*log /tmp/gauge*log /tmp/faucet-tests* ; killall ryu-manager ; ./faucet_mininet_test.py -c ; ./test_config.py && ./test_valve.py && /usr/local/share/openvswitch/scripts/ovs-ctl stop ; /usr/local/share/openvswitch/scripts/ovs-ctl start ; ./faucet_mininet_test.py $*
