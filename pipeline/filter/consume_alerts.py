"""Consumes stream for ingesting to database
"""
from __future__ import print_function
import os, sys
sys.path.append('../../common')
from src import date_nid, slack_webhook, db_connect
from src.manage_status import manage_status
import settings

from multiprocessing import Process, Manager
from features_ZTF import insert_query
import confluent_kafka
import argparse, time, json
import signal

# If we catch a SIGTERM, set a flag
sigterm_raised = False

def sigterm_handler(signum, frame):
    global sigterm_raised
    sigterm_raised = True

signal.signal(signal.SIGTERM, sigterm_handler)


sherlock_attributes = [
    "classification",
    "objectId",
    "association_type",
    "catalogue_table_name",
    "catalogue_object_id",
    "catalogue_object_type",
    "raDeg",
    "decDeg",
    "separationArcsec",
    "northSeparationArcsec",
    "eastSeparationArcsec",
    "physical_separation_kpc",
    "direct_distance",
    "distance",
    "z",
    "photoZ",
    "photoZErr",
    "Mag",
    "MagFilter",
    "MagErr",
    "classificationReliability",
    "major_axis_arcsec",
    "annotator",
    "additional_output",
    "description",
    "summary",
]

def parse_args():
    """parse_args.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=str,
                        help='Hostname or IP of Kafka host to connect to.')

    parser.add_argument('--topic_in', type=str,
                        help='Name of Kafka topic to listen to.')

    parser.add_argument('--group', type=str,
                        help='Globally unique name of the consumer group. '
                        'Consumers in the same group will share messages '
                        '(i.e., only one consumer will receive a message, '
                        'as in a queue). Default is value of $HOSTNAME.')

    parser.add_argument('--maxalert', type=int,
                        help='Max alerts to be fetched per process')

    parser.add_argument('--nprocess', type=int,
                        help='Number of process to use')

    args = parser.parse_args()
    return args

def execute_query(query, msl):
    try:
        cursor = msl.cursor(buffered=True)
        cursor.execute(query)
        cursor.close()
        msl.commit()
    except mysql.connector.Error as err:
        print('ERROR filter/consume_alerts: object Database insert candidate failed: %s' % str(err))
        print(query)
        sys.stdout.flush()

def alert_filter(alert, msl):
    """alert_filter.

    Args:
        alert:
        msl:
    """
    # Filter to apply to each alert.
    objectId = alert['objectId']

    if not 'candid' in alert['candidate'] or not alert['candidate']['candid']:
        return {'objects':0, 'candidates':0} 

    # build the insert query for this object.
    # if not wanted, returns None
    iq_dict = insert_query.create_insert_query(alert)
    if not iq_dict:
        return {'ss':0, 'nalert':0}
    query = iq_dict['query']
    ss = iq_dict['ss']

    # lets not fill up the database with SS detections right now
    if ss == 0:   
        execute_query(query, msl)

    # now ingest the sherlock_classifications
    if 'annotations' in alert:
        annotations = alert['annotations']
        annClass = 'sherlock'
        if annClass in annotations:
            for ann in annotations[annClass]:
                if "transient_object_id" in ann:
                    ann.pop('transient_object_id')
                ann['objectId'] = objectId

                query = insert_query.create_insert_annotation(objectId, annClass, ann, 
                    sherlock_attributes, 'sherlock_classifications', replace=True)
#                f = open('data/%s_sherlock.json'%objectId, 'w')
#                f.write(query)
#                f.close()
                execute_query(query, msl)
    return {'ss':iq_dict['ss'], 'nalert':1}

def run(runarg, return_dict):
    """run.
    """
    processID = runarg['processID']
    # Configure database connection
    try:
        msl = db_connect.local()
    except Exception as e:
        print('ERROR cannot connect to local database', e)
        sys.stdout.flush()
        return

    # Start consumer and print alert stream
    try:
        consumer = confluent_kafka.Consumer(**runarg['conf'])
        consumer.subscribe([runarg['args'].topic_in])
    except Exception as e:
        print('ERROR cannot connect to kafka', e)
        sys.stdout.flush()
        return

    # Number of alerts in the batch
    if runarg['args'].maxalert:
        maxalert = runarg['args'].maxalert
    else:
        maxalert = 50000

    nalert_in = nalert_out = nalert_ss = 0
    startt = time.time()
    while nalert_in < maxalert:
        if sigterm_raised:
            # clean shutdown - stop the consumer and commit offsets
            print("Caught SIGTERM, aborting.")
            sys.stdout.flush()
            break

        # Here we get the next alert by kafka
        msg = consumer.poll(timeout=5)
        if msg is None:
            break
        if msg.error():
            continue
        if msg.value() is None:
            continue
        else:
            # Apply filter to each alert
            alert = json.loads(msg.value())
            nalert_in += 1
            d = alert_filter(alert, msl)
            nalert_out += d['nalert']
            nalert_ss  += d['ss']
            if nalert_in%1000 == 0:
                print('process %d nalert_in %d nalert_out  %d time %.1f' % 
                    (processID, nalert_in, nalert_out, time.time()-startt))
                sys.stdout.flush()
                # refresh the database every 1000 alerts
                # make sure everything is committed
                msl.close()
                msl = db_connect.local()

    consumer.close()
    return_dict[processID] = {
            'nalert_in':nalert_in, 
            'nalert_out': nalert_out, 
            'nalert_ss':nalert_ss 
            }


def main():
    """main.
    """
    args = parse_args()

    # Configure consumer connection to Kafka broker
    conf = {
        'bootstrap.servers': '%s' % args.host,
        'default.topic.config': {
             'auto.offset.reset': 'smallest'
        }}
    if args.group: conf['group.id'] = args.group
    else:          conf['group.id'] = 'LASAIR'
    print('Configuration = %s' % str(conf))

    # How many processs
    if args.nprocess: nprocess = args.nprocess
    else:             nprocess = 1
    print('Processes = %d' % nprocess)
    sys.stdout.flush()

    runargs = []
    process_list = []
    manager = Manager()
    return_dict = manager.dict()
    t = time.time()
    for t in range(nprocess):
        runarg = {
            'processID':t,
            'args':args,
            'conf':conf,
        }
        p = Process(target=run, args=(runarg, return_dict))
        process_list.append(p)
        p.start()

    for p in process_list:
        p.join()

    r = return_dict.values()
    nalert_in = nalert_out = nalert_ss = 0
    for t in range(nprocess):
        nalert_in  += r[t]['nalert_in']
        nalert_out += r[t]['nalert_out']
        nalert_ss  += r[t]['nalert_ss']

    print('INGEST finished %d in, %d out, %d solar system' % (nalert_in, nalert_out, nalert_ss))
    sys.stdout.flush()

    ms = manage_status(settings.SYSTEM_STATUS)
    nid  = date_nid.nid_now()
    ms.add({
        'today_filter':nalert_in, 
        'today_filter_out':nalert_out,
        'today_filter_ss':nalert_ss
        }, nid)

    if nalert_in > 0: return 1
    else:             return 0

if __name__ == '__main__':
    try:
        rc = main()
        sys.exit(rc)
    except Exception as e:
        rtxt = "ERROR in filter/consume_alerts"
        rtxt += str(e)
        slack_webhook.send(settings.SLACK_URL, rtxt)
        print(rtxt)
        sys.stdout.flush()
        sys.exit(-1)

