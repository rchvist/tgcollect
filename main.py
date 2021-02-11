import time
import datetime
import pytz
utc=pytz.UTC
from common import config, logger
from database import Database
from elastic import ES, translate_message_for_es
from model import Message, Channel
from telegram import SyncTelegramClient

db = Database(
    "dbname='telegram' user='postgres' host='localhost' password='%s'"
    % (config["db_password"],)
)

es = ES(
    config["es_host"],
    config["es_index"],
)

telethon_api = SyncTelegramClient()


def ingest_channel(channel_name: str, channel_id: int, stop_point: int = None):
    BATCH_SIZE = 250
    current_message_id = None
    max_message_id = None
    min_message_id = None
    total_messages = 0
    seen_ids = set()
    stop_flag = False
    min_date = datetime.datetime(2020, 1,1)
    min_date= utc.localize(min_date)

    while True:
        es_records = []
        pg_records = []
        if current_message_id ==1 :
            stop_flag = True
        logger.debug(
            "Fetching %d ids (in descending order) from %s starting at id %s. current_message_id is of type %s" %
            (BATCH_SIZE, channel_name, current_message_id, type(current_message_id))
        )

        messages = telethon_api.fetch_messages(
            channel=channel_name,
            size=BATCH_SIZE,
            max_id=current_message_id,
        )

        retrieved_utc = int(time.time())
        
        

        for m in messages:
            message_id = m.id
            if stop_point and message_id <= stop_point:
                stop_flag = True
                break
            if m.date <= min_date :
                stop_flag = True
                break
            if message_id in seen_ids:
                logger.warning("Message id %d was already ingested" % (message_id,))
            seen_ids.add(message_id)
            total_messages += 1
            if current_message_id is None or message_id < current_message_id:
                current_message_id = message_id
            if min_message_id is None or message_id < min_message_id:
                min_message_id = message_id
            if max_message_id is None or message_id > max_message_id:
                max_message_id = message_id
            message_channel_id = m.to_id.channel_id
            if message_channel_id != channel_id:
                logger.warning("Message channel id for %s does not match"
                               "expected value. %d != %d" %
                               (channel_name, message_channel_id, channel_id))
            record_id = (message_channel_id << 32) + message_id
            data = m.to_json()
            updated_utc = retrieved_utc
            es_records.append(translate_message_for_es(m, channel_name, retrieved_utc))

            pg_records.append(Message(
                record_id=record_id,
                message_id=message_id,
                channel_id=channel_id,
                retrieved_utc=retrieved_utc,
                updated_utc=updated_utc,
                data=data,
            ))
        logger.warning("On est sorti du loop. La valeur de stop_flag est %s" %
                            str(stop_flag))
        db.insert_messages(pg_records)
        es.bulk_insert(es_records)
        if stop_flag:
            break
        time.sleep(1)  # TODO: rate limit decorator

    logger.debug("A total of %d messages were ingested for channel %s" %
                 (total_messages, channel_name))

    # TODO: Should we update this at every iteration?
    #  This way if this crashes halfway through it can resume
    if total_messages > 0:
        db.upsert_channel(Channel(
            channel_id=channel_id,
            channel_name=channel_name,
            updated_utc=int(time.time()),
            retrieved_utc=int(time.time()),
            min_message_id=min_message_id,
            max_message_id=max_message_id,
            is_active=True,
            is_complete=True,
        ))


if __name__ == "__main__":
    # TODO close file
    channels = open("channels_to_add.csv", "r").read().split("\n")
    channels = [channel for channel in channels if channel != ""]

    for channel in channels:

        channel_data = telethon_api.get_channel_info(channel) 
        #appel à l'API telethon qui récupère les données de la chaîne en JSON

        channel_id = channel_data["full_chat"]["id"]
        channel_name = channel_data["chats"][0]["username"]
        channel_info = db.get_channel_by_id(channel_id)
        #cherche dans la table "channel" : "SELECT * FROM channel WHERE id = channel_id

        # If the channel is not in the DB, let's get the entire history for the channel
        if channel_info is None:
            db.upsert_channel_data(channel_id, channel_data)
            #si le channel n'est pas dans la db channel, 
            #insère les infos dans la db channel_data. le PARAM channel_data est un json
            ingest_channel(channel, channel_id)
            #ingest_channel prévoit d'ajouter une ligne dans la db Channel mais seulement
            #après avoir break la loop
        else:
            ingest_channel(channel, channel_id, channel_info[5])

