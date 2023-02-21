import logging
import requests
import os
import subprocess

from sqlalchemy.exc import NoResultFound

from hw_diag.utilities.balena_supervisor import BalenaSupervisor
from hw_diag.database import get_db_session
from hw_diag.database.models.auth import AuthKeyValue
from hw_diag.utilities.auth import generate_default_password

HPT_IP = '192.168.220.1'  # NOSONAR


def get_wan_ip_address():
    try:
        resp = requests.get('https://icanhazip.com')
        return resp.text
    except Exception:
        return None


def device_in_manufacturing_network() -> bool:
    # one can set the device in manufacturing though env var
    in_manufacturing_env = os.getenv('IN_MANUFACTURING', 'false')
    in_manufacturing = in_manufacturing_env.lower() in ('true', '1', 't')
    if in_manufacturing:
        return in_manufacturing

    # in manufacturing if hpt is reachable
    logging.info(f"lets ping hpt to detect network. HPT: {HPT_IP}")
    try:
        # ping without count 2s, interval  0.5s and timeout of 1s
        cmd = ['ping', '-c', '2', '-i', '0.5', '-W', '1', HPT_IP]
        subprocess.check_call(cmd)
        in_manufacturing = True
    except Exception as e:
        logging.error(f"failed to ping hpt : {HPT_IP}")
        logging.error(e)
    return in_manufacturing


def device_in_manufacturing():
    path_exists = False
    filename = '/var/nebra/in_manufacturing'
    if os.path.exists(filename):
        path_exists = True
        # remove the file as we want this to happen only once.
        os.remove(filename)
    return path_exists or device_in_manufacturing_network()


def get_device_hostname():
    try:
        balena_supervisor = BalenaSupervisor.new_from_env()
        device_config = balena_supervisor.get_device_config()
        network = device_config.get('network')
        hostname = network.get('hostname')
    except Exception:
        hostname = None
    return hostname


def setup_hostname():
    # This runs before the Flask app is really fully running, so we do not have the
    # global "g" object with the db session, so we must spawn our own.
    db = get_db_session()
    HOSTNAME_SET_KEY = 'hostname_set'
    try:
        try:
            hostname_set_row = db.query(AuthKeyValue). \
                filter(AuthKeyValue.key == HOSTNAME_SET_KEY). \
                one()
        except NoResultFound:
            hostname_set_row = AuthKeyValue(
                key=HOSTNAME_SET_KEY,
                value='false'
            )
            db.add(hostname_set_row)
            db.commit()

        # We don't use boolean here because the field in the DB is a string as we have
        # some general key value pair table with string values. Sorry bros :-(
        if hostname_set_row.value == 'false':
            logging.info("Hostname not set yet...")
            # Set hostname via Balena supervisor...
            default_password = generate_default_password()
            hostname_suffix = default_password[6:]
            hostname = "nebra-%s.local" % hostname_suffix
            balena_supervisor = BalenaSupervisor.new_from_env()
            balena_supervisor.set_hostname(hostname)
            hostname_set_row.value = 'true'
            db.commit()
        else:
            logging.info("Hostname already set!")

        db.close_all()
    except Exception as err:
        logging.error("Error setting hostname: %s" % str(err))
        db.close_all()
    finally:
        db.close_all()
