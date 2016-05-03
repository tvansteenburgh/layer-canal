import os
from shlex import split
from subprocess import check_call

from charms.docker import DockerOpts

from charms.reactive import set_state
from charms.reactive import when
from charms.reactive import when_not

from charmhelpers.core.hookenv import status_set
from charmhelpers.core import unitdata
from charmhelpers.core import host

import charms.apt

# Network Port Map
# protocol | port | source       | purpose
# ----------------------------------------------------------------------
# UDP     | 8285  | worker nodes | Flannel overlay network - UDP Backend.
# UDP     | 8472  | worker nodes | Flannel overlay network - vxlan backend


# Example subnet.env file
# FLANNEL_NETWORK=10.1.0.0/16
# FLANNEL_SUBNET=10.1.57.1/24
# FLANNEL_MTU=1450
# FLANNEL_IPMASQ=false

@when('docker.ready')
@when_not('etcd.connected')
def halt_execution():
    status_set('blocked', 'Pending etcd relation.')


@when('docker.ready', 'etcd.available')
def run_bootstrap_daemons(etcd):
    ''' Starts a bootstrap docker service on /var/run/docker-bootstrap.sock
        fetches ETCD, Flannel, and starts the services. This method will halt
        a running Docker daemon started by systemd/upstart. Not to be run after
        initial job completion'''

    cmd = "scripts/bootstrap_docker.sh {}".format(etcd.connection_string())
    check_call(split(cmd))
    ingest_network_config()
    set_state('sdn.available')


def ingest_network_config():
    '''Ingest the environment file with the subnet information, and parse it
    for data to be consumed in charm logic. '''
    db = unitdata.kv()
    opts = DockerOpts()

    if db.get('sdn_subnet') and db.get('sdn_mtu'):
        # We have values, and are possibly good to go
        return

    if not os.path.isfile('subnet.env'):
        status_set('waiting', 'No subnet file to ingest.')
        return

    with open('subnet.env') as f:
        flannel_config = f.readlines()

    for f in flannel_config:
        if "FLANNEL_SUBNET" in f:
            value = f.split('=')[-1].strip()
            db.set('sdn_subnet', value)
            opts.add('bip', value)
        if "FLANNEL_MTU" in f:
            value = f.split('=')[1].strip()
            db.set('sdn_mtu', value)
            opts.add('mtu', value)


@when('flannel.configuring')
def reconfigure_docker_for_sdn():
    status_set('maintenance', 'Configuring docker daemon for Flannel Networking')
    cmd = "ifconfig docker0 down"
    check_call(split(cmd))

    charms.apt.queue_install(['bridge-utils'])

    cmd = "brctl delbr docker0"
    check_call(split(cmd))

    set_state('docker.restart')
