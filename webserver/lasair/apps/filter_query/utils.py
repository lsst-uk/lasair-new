from lasair.query_builder import check_query, build_query
from src import db_connect
from lasair.apps.db_schema.utils import get_schema, get_schema_dict, get_schema_for_query_selected
from lasair.utils import datetime_converter


def add_filter_query_metadata(
        filter_queries,
        remove_duplicates=False):
    """*add extra metadata to the filter_queries and return a list of filter_queries dictionaries*

    **Key Arguments:**

    - `filter_queries` -- a list of filter_query objects
    - `remove_duplicates` -- remove duplicate filters 

    **Usage:**

    ```python
    filterQueryDicts = add_filter_query_metadata(filter_queries)
    ```           
    """
    # from lasair.watchlist.models import Watchlist, WatchlistCone
    updatedFilterQueryLists = []
    real_sql = []
    for fqDict, fq in zip(filter_queries.values(), filter_queries):
        # ADD LIST COUNT
        # fqDict['count'] = WatchlistCone.objects.filter(wl_id=wlDict['wl_id']).count()

        # ADD LIST USER
        if not remove_duplicates or fq.real_sql not in real_sql:
            fqDict['user'] = f"{fq.user.first_name} {fq.user.last_name}"
            fqDict['profile_image'] = fq.user.profile.image_b64
            updatedFilterQueryLists.append(fqDict)
            real_sql.append(fq.real_sql)
        else:
            print("GONE")
    return updatedFilterQueryLists


def run_filter(
        selected,
        tables,
        conditions,
        limit,
        offset,
        mq_id=False,
        query_name=False):
    """run the filter and return the table of results

    **Key Arguments:**

        - `userid` -- the users unique ID
        - `name` -- the name given to the filter

    """
    message = ''
    error = check_query(selected, tables, conditions)
    if error:
        return None, None, None, None, error
    sqlquery_real = build_query(selected, tables, conditions)
    sqlquery_limit = sqlquery_real + ' LIMIT %d OFFSET %d' % (limit, offset)
    message += sqlquery_limit

    nalert = 0
    msl = db_connect.readonly()
    cursor = msl.cursor(buffered=True, dictionary=True)

    if query_name:
        topic = topic_name(mq_id, query_name)
    else:
        topic = False

    try:
        cursor.execute(sqlquery_limit)
    except Exception as e:
        error = 'Your query:<br/><b>' + sqlquery_limit + '</b><br/>returned the error<br/><i>' + str(e) + '</i>'
        return None, None, None, None, error

    table = []
    for row in cursor:
        table.append(row)
        nalert += 1

    tableSchema = get_schema_for_query_selected(selected)
    if len(table):
        for k in table[0].keys():
            if k not in tableSchema:
                tableSchema[k] = "custom column"

    return table, tableSchema, nalert, topic, error

    if json_checked:
        return HttpResponse(json.dumps(table, indent=2), content_type="application/json")
    else:
        return render(request, 'filter_query/filter_query_detail.html',
                      {'table': table, 'nalert': nalert,
                       'topic': topic,
                       'title': query_name,
                       'mq_id': mq_id,
                       'selected': selected,
                       'tables': tables,
                       'conditions': conditions,
                       'nalert': nalert,
                       'ps': offset, 'pe': offset + nalert,
                       'limit': limit, 'offset': offset,
                       'message': message,
                       "schema": tableSchema})


def topic_name(userid, name):
    """generate a kafka topic name based on userid and query name.

    **Key Arguments:**

        - `userid` -- the users unique ID
        - `name` -- the name given to the filter

    """
    name = ''.join(e for e in name if e.isalnum() or e == '_' or e == '-' or e == '.')
    return 'lasair_' + '%d' % userid + name


def check_query_zero_limit(real_sql):
    """*use a limit of zero to test the validity of the query*

    **Key Arguments:**

    - `real_sql` -- the full SQL query

    **Usage:**

    ```python
    from lasair.apps.filter_query.utils import check_query_zero_limit
    e = check_query_zero_limit(real_sql)
    ```
    """
    msl = db_connect.readonly()
    cursor = msl.cursor(buffered=True, dictionary=True)

    try:
        cursor.execute(real_sql + ' LIMIT 0')
        return None
    except Exception as e:
        message = 'Your query:<br/><b>' + real_sql + '</b><br/>returned the error<br/><i>' + str(e) + '</i>'
        return message


def topic_refresh(real_sql, topic, limit=10):
    """*refresh a kafka topic on creation or update of a filter*

    **Key Arguments:**

    - `real_sql` -- the full SQL query
    - `topic` -- the topic name to update
    - `limit` -- the number of items to add to the topic initially

    **Usage:**

    ```python
    from lasair.apps.filter_query.utils import topic_refresh
    topic_refresh(filterQuery.real_sql, tn, limit=10)
    ```
    """
    message = ''
    msl = db_connect.readonly()
    cursor = msl.cursor(buffered=True, dictionary=True)
    query = real_sql + ' LIMIT %d' % limit

    try:
        cursor.execute(query)
    except Exception as e:
        message += 'Your query:<br/><b>' + query + '</b><br/>returned the error<br/><i>' + str(e) + '</i><br/>'
        return message

    recent = []
    for record in cursor:
        recorddict = dict(record)
        now_number = datetime.utcnow()
        recorddict['UTC'] = now_number.strftime("%Y-%m-%d %H:%M:%S")
        print(recorddict)
        recent.append(recorddict)

    conf = {
        'bootstrap.servers': settings.PUBLIC_KAFKA_SERVER,
        'security.protocol': 'SASL_PLAINTEXT',
        'sasl.mechanisms': 'SCRAM-SHA-256',
        'sasl.username': 'admin',
        'sasl.password': settings.PUBLIC_KAFKA_PASSWORD
    }

    # delete the old topic
    a = admin.AdminClient(conf)

    try:
        result = a.delete_topics([topic])
        result[topic].result()
        time.sleep(1)
        message += 'Topic %s deleted<br/>' % topic
    except Exception as e:
        message += 'Topic is ' + topic + '<br/>'
        message += str(e) + '<br/>'

    # pushing in new messages will remake the topic
    try:
        p = Producer(conf)
        for out in recent:
            jsonout = json.dumps(out, default=datetime_converter)
            p.produce(topic, value=jsonout)
        p.flush(10.0)   # 10 second timeout
        message += '%d new messages produced to topic %s<br/>' % (limit, topic)
    except Exception as e:
        message += "ERROR in queries/topic_refresh: cannot produce to public kafka<br/>" + str(e) + '<br/>'
    return message


def delete_stream_file(request, query_name):
    """*delete a filter kafka log file*

    **Key Arguments:**

    - `request` -- original request
    - `query_name` -- the filter stream to delete

    **Usage:**

    ```python
    from lasair.apps.filter_query.utils import delete_stream_file
    delete_stream_file(request, filterQuery.name)
    ```
    """
    topic = topic_name(request.user.id, query_name)
    filename = settings.KAFKA_STREAMS + topic
    if os.path.exists(filename):
        os.remove(filename)
