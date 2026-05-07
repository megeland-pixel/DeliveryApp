from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
import pyodbc
from datetime import date, datetime
import urllib.parse
import logging
import sqlite3
import json
import os
import requests
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['TEMPLATES_AUTO_RELOAD'] = True
logging.basicConfig(level=logging.INFO)

DELIVERY_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deliveries.db')


def init_db():
    with sqlite3.connect(DELIVERY_DB) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_date TEXT NOT NULL,
                driver TEXT NOT NULL,
                truck TEXT NOT NULL,
                delivery_order TEXT NOT NULL,
                so_nums TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                UNIQUE(delivery_date, driver, truck, delivery_order)
            )
        ''')
        for col in ('signature TEXT', 'customer TEXT'):
            try:
                conn.execute(f'ALTER TABLE deliveries ADD COLUMN {col}')
            except Exception:
                pass
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sms_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_date TEXT NOT NULL,
                driver TEXT NOT NULL,
                truck TEXT NOT NULL,
                delivery_order TEXT NOT NULL,
                sent_at TEXT NOT NULL
            )
        ''')


def format_time(iso_str):
    if not iso_str:
        return ''
    try:
        dt = datetime.fromisoformat(iso_str)
        hour = dt.hour % 12 or 12
        return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except Exception:
        return ''


def get_last_texts_for_driver(delivery_date, driver):
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            rows = conn.execute(
                '''SELECT truck, delivery_order, MAX(sent_at)
                   FROM sms_logs
                   WHERE delivery_date=? AND driver=?
                   GROUP BY truck, delivery_order''',
                (delivery_date, driver)
            ).fetchall()
        return {(row[0], row[1]): format_time(row[2]) for row in rows}
    except Exception:
        return {}


def get_last_text(delivery_date, driver, truck, delivery_order):
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            row = conn.execute(
                '''SELECT MAX(sent_at) FROM sms_logs
                   WHERE delivery_date=? AND driver=? AND truck=? AND delivery_order=?''',
                (delivery_date, driver, truck, delivery_order)
            ).fetchone()
        return format_time(row[0]) if row and row[0] else ''
    except Exception:
        return ''


def get_delivered_keys(delivery_date, driver):
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            rows = conn.execute(
                'SELECT truck, delivery_order FROM deliveries WHERE delivery_date = ? AND driver = ?',
                (delivery_date, driver)
            ).fetchall()
        return {(row[0], row[1]) for row in rows}
    except Exception:
        return set()


init_db()


SCHEDULE_QUERY = """
SELECT
    RTRIM(C.NAME_CUSTOMER) AS customer,
    H.ORDER_NO AS so_num,
    COALESCE(CONCAT(CONCAT(CAST(X.JOB AS VARCHAR(20)), '-'), CAST(X.SUFFIX AS VARCHAR(20))), 'STOCK') AS wo_num,
    RTRIM(H.CODE_SORT) AS wu_person,
    CASE
        WHEN H.MARK_INFO = '' THEN ''
        WHEN LOCATE('/', H.MARK_INFO) > 0 THEN SUBSTRING(RTRIM(H.MARK_INFO), 5, LOCATE('/', H.MARK_INFO) - 5)
        ELSE SUBSTRING(RTRIM(H.MARK_INFO), 5)
    END AS driver,
    CASE
        WHEN H.MARK_INFO = '' THEN ''
        WHEN LOCATE('/', H.MARK_INFO) > 0 THEN SUBSTRING(RTRIM(H.MARK_INFO), LOCATE('/', H.MARK_INFO) + 6)
        ELSE '1'
    END AS truck,
    COALESCE(RTRIM(X.PART), 'STOCK') AS line_item,
    COALESCE(RTRIM(O.PART), 'STOCK') AS step,
    COALESCE(S.sumEst, 0) AS estimated,
    COALESCE(S.sumAct, 0) AS actual,
    UPPER(LTRIM(RTRIM(N.JOB_NOTE))) AS notes,
    CASE
        WHEN LTRIM(RTRIM(SUBSTRING(H.MARK_INFO, 3, 1))) = '' THEN '99'
        ELSE SUBSTRING(H.MARK_INFO, 3, 1)
    END AS delivery_order,
    RTRIM(LTRIM(H.MARK_INFO)) AS mark_info,
    CT.CALL_DATE AS called,
    RTRIM(COALESCE(ST.ADDRESS_1_SHIP, '')) AS address_1,
    RTRIM(COALESCE(ST.ADDRESS_2_SHIP, '')) AS address_2,
    RTRIM(COALESCE(ST.ADDRESS_3_SHIP, '')) AS address_3,
    RTRIM(COALESCE(ST.ADDRESS_4_SHIP, '')) AS address_4,
    RTRIM(COALESCE(ST.ADDRESS_5_SHIP, '')) AS address_5,
    RTRIM(COALESCE(ST.CITY_SHIP, '')) AS city,
    RTRIM(COALESCE(ST.STATE_SHIP, '')) AS state,
    RTRIM(COALESCE(ST.CODE_ZIP_SHIP, '')) AS zip,
    RTRIM(COALESCE(BT.CONTACT, '')) AS contact,
    RTRIM(COALESCE(BT.CONTACT_PHONE, '')) AS phone
FROM V_ORDER_HEADER H
INNER JOIN V_CUSTOMER_MASTER C ON H.CUSTOMER = C.CUSTOMER
LEFT JOIN V_ORDER_TO_WO X ON H.ORDER_NO = X.ORDER_NO
LEFT JOIN XMOG_SO_NOTES N ON H.ORDER_NO = N.ORDER_NO
LEFT JOIN (
    SELECT JOB, SUFFIX, MIN(CAST(SEQ AS INTEGER)) AS MinSeq
    FROM V_JOB_OPERATIONS
    WHERE UNITS_OPEN > UNITS_COMPLETE
    GROUP BY JOB, SUFFIX
) M ON M.JOB = X.JOB AND M.SUFFIX = X.SUFFIX
LEFT JOIN (
    SELECT JOB, SUFFIX, SUM(HOURS_ESTIMATED) AS sumEst, SUM(HOURS_ACTUAL) AS sumAct
    FROM V_JOB_OPERATIONS
    WHERE LMO = 'L'
    GROUP BY JOB, SUFFIX
) S ON S.JOB = X.JOB AND S.SUFFIX = X.SUFFIX
LEFT JOIN V_JOB_OPERATIONS O
    ON O.JOB = M.JOB AND O.SUFFIX = M.SUFFIX
    AND CAST(O.SEQ AS INTEGER) = M.MinSeq AND O.LMO = 'L'
LEFT JOIN (
    SELECT C.ORDER_NO, C.CALL_DATE
    FROM MDE_orderCall C
    INNER JOIN (
        SELECT ORDER_NO, MAX(CALL_ID) AS MaxCallID
        FROM MDE_orderCall
        GROUP BY ORDER_NO
    ) M ON C.ORDER_NO = M.ORDER_NO AND C.CALL_ID = M.MaxCallID
) CT ON H.ORDER_NO = CT.ORDER_NO
LEFT JOIN V_ORDER_SHIP_TO ST ON H.ORDER_NO = ST.ORDER_NO
LEFT JOIN V_ORDER_BILL_TO BT ON H.ORDER_NO = BT.ORDER_NO
INNER JOIN (
    SELECT DISTINCT ORDER_NO
    FROM V_ORDER_LINES
    WHERE PART LIKE 'FRT%'
    AND DATE_ITEM_PROM = ?
) FRT ON FRT.ORDER_NO = H.ORDER_NO
WHERE H.SHIP_VIA NOT LIKE '%Pick Up%'
ORDER BY
    CASE WHEN RTRIM(SUBSTRING(H.MARK_INFO, 5)) = '' THEN 1 ELSE 0 END,
    6, 12, 5, 3 ASC
"""


def get_db_connection():
    return pyodbc.connect(DSN=config.DSN_NAME, UID=config.DB_USER, PWD=config.DB_PASSWORD)


def fetch_stops(delivery_date):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(SCHEDULE_QUERY, (delivery_date,))
        columns = [col[0] for col in cursor.description]
        rows = []
        for row in cursor.fetchall():
            stop = dict(zip(columns, row))

            # Pad SO number to 7 digits with leading zeros
            stop['so_num'] = str(stop['so_num']).zfill(7)

            # Normalize any None values to empty strings for string fields
            for key in ('address_1', 'address_2', 'address_3', 'address_4', 'address_5',
                        'city', 'state', 'zip', 'contact', 'phone', 'notes', 'driver', 'wo_num'):
                if stop.get(key) is None:
                    stop[key] = ''

            # Format called date if it came back as a date/datetime object
            called = stop.get('called')
            if called and hasattr(called, 'strftime'):
                stop['called'] = called.strftime('%m/%d/%Y')
            elif called:
                stop['called'] = str(called)

            # Address line 1: all non-empty street lines joined
            stop['address_street'] = ', '.join(
                stop[k] for k in ('address_1', 'address_2', 'address_3', 'address_4', 'address_5') if stop[k]
            )
            # Address line 2: City, State Zip
            city_state = ', '.join(p for p in [stop['city'], stop['state']] if p)
            stop['address_city_line'] = (city_state + ' ' + stop['zip']).strip() if city_state else stop['zip']

            # For geocoding/maps, skip C/O and ATTN lines to get the actual street address
            _skip = ('C/O', 'ATTN', 'ATTENTION', 'IN CARE OF')
            street_for_geo = next(
                (stop[k] for k in ('address_1', 'address_2', 'address_3', 'address_4', 'address_5')
                 if stop[k] and not stop[k].upper().startswith(_skip)),
                ''
            )
            # Require at least a city to consider this a routable address;
            # bare codes like "EDI" with no city/state geocode to wrong places.
            if stop['city']:
                maps_parts = [p for p in [street_for_geo, stop['city'], stop['state'], stop['zip']] if p]
                maps_addr = ', '.join(maps_parts)
            else:
                maps_addr = ''
            stop['display_address'] = maps_addr
            stop['maps_url'] = (
                'https://www.google.com/maps/dir/?api=1&destination=' + urllib.parse.quote(maps_addr)
            ) if maps_addr else ''

            rows.append(stop)
        return rows
    finally:
        conn.close()


def group_stops_by_order(stops):
    """One card per (truck, delivery_order) load — lists all SO#s on that load."""
    seen = {}
    result = []
    for stop in stops:
        key = (stop['driver'], stop['truck'], stop['delivery_order'])
        if key not in seen:
            entry = stop.copy()
            entry['so_list'] = [stop['so_num']]
            seen[key] = entry
            result.append(entry)
        else:
            if stop['so_num'] not in seen[key]['so_list']:
                seen[key]['so_list'].append(stop['so_num'])
    return result


@app.route('/sms-consent')
def sms_consent():
    return render_template('sms_consent.html', year=date.today().year)


@app.route('/sw.js')
def service_worker():
    return send_from_directory(app.static_folder, 'sw.js',
                               mimetype='application/javascript')


@app.route('/')
def index():
    selected_date = date.today().isoformat()
    try:
        all_stops = fetch_stops(selected_date)
        drivers = sorted(set(s['driver'] for s in all_stops if s.get('driver')))

        truck_data = {}
        for driver in drivers:
            driver_stops = [s for s in all_stops if s.get('driver') == driver]
            grouped = group_stops_by_order(driver_stops)
            delivered_keys = get_delivered_keys(selected_date, driver)
            counts = {}
            for stop in grouped:
                t = stop['truck']
                if t not in counts:
                    counts[t] = {'stop_count': 0, 'delivered_count': 0}
                counts[t]['stop_count'] += 1
                if (t, stop['delivery_order']) in delivered_keys:
                    counts[t]['delivered_count'] += 1
            trucks = []
            for t, d in counts.items():
                all_delivered = d['stop_count'] > 0 and d['delivered_count'] == d['stop_count']
                trucks.append({'truck': t, 'stop_count': d['stop_count'], 'all_delivered': all_delivered})
            trucks.sort(key=lambda x: (x['all_delivered'], x['truck']))
            truck_data[driver] = trucks

        error = None
    except Exception as e:
        app.logger.error(f'DB error on index: {e}')
        drivers = []
        truck_data = {}
        error = 'Could not connect to the database. Check DSN configuration.'
    return render_template('index.html', selected_date=selected_date, drivers=drivers,
                           truck_data=truck_data, error=error)


@app.route('/api/drivers')
def api_drivers():
    selected_date = request.args.get('date', date.today().isoformat())
    try:
        all_stops = fetch_stops(selected_date)
        drivers = sorted(set(s['driver'] for s in all_stops if s.get('driver')))
        return jsonify({'drivers': drivers})
    except Exception as e:
        app.logger.error(f'DB error on api_drivers: {e}')
        return jsonify({'drivers': [], 'error': str(e)}), 500


@app.route('/api/trucks')
def api_trucks():
    selected_date = request.args.get('date', date.today().isoformat())
    driver = request.args.get('driver', '').strip()
    if not driver:
        return jsonify({'trucks': []})
    try:
        all_stops = fetch_stops(selected_date)
        driver_stops = [s for s in all_stops if s.get('driver') == driver]
        grouped = group_stops_by_order(driver_stops)
        delivered_keys = get_delivered_keys(selected_date, driver)

        truck_data = {}
        for stop in grouped:
            t = stop['truck']
            if t not in truck_data:
                truck_data[t] = {'stop_count': 0, 'delivered_count': 0}
            truck_data[t]['stop_count'] += 1
            if (t, stop['delivery_order']) in delivered_keys:
                truck_data[t]['delivered_count'] += 1

        trucks = []
        for t, d in truck_data.items():
            all_delivered = d['stop_count'] > 0 and d['delivered_count'] == d['stop_count']
            trucks.append({'truck': t, 'stop_count': d['stop_count'], 'all_delivered': all_delivered})

        trucks.sort(key=lambda x: (x['all_delivered'], x['truck']))
        return jsonify({'trucks': trucks})
    except Exception as e:
        app.logger.error(f'DB error on api_trucks: {e}')
        return jsonify({'trucks': [], 'error': str(e)}), 500


@app.route('/schedule')
def schedule():
    driver = request.args.get('driver', '').strip()
    truck = request.args.get('truck', '').strip()
    selected_date = date.today().isoformat()
    if not driver or not truck:
        return redirect(url_for('index'))
    try:
        all_stops = fetch_stops(selected_date)
        driver_stops = [s for s in all_stops if s.get('driver') == driver and s.get('truck') == truck]
        stops = group_stops_by_order(driver_stops)
        delivered_keys = get_delivered_keys(selected_date, driver)
        last_texts = get_last_texts_for_driver(selected_date, driver)
        for stop in stops:
            stop['delivered'] = (stop['truck'], stop['delivery_order']) in delivered_keys
            stop['last_text_sent'] = last_texts.get((stop['truck'], stop['delivery_order']), '')
        # Delivered stops go to the bottom
        stops.sort(key=lambda s: s['delivered'])
        error = None
    except Exception as e:
        app.logger.error(f'DB error on schedule: {e}')
        stops = []
        error = 'Could not load schedule.'
    return render_template('schedule.html',
                           driver=driver,
                           truck=truck,
                           selected_date=selected_date,
                           stops=stops,
                           company=config.COMPANY_NAME,
                           error=error)


_geocode_cache = {}


def geocode_address(address):
    if address in _geocode_cache:
        return _geocode_cache[address]

    # Build structured query from "street, city, state, zip" format for better accuracy
    parts = [p.strip() for p in address.split(',')]
    base = {'format': 'json', 'limit': 1, 'countrycodes': 'us'}
    if len(parts) >= 4:
        street, city, state, zipcode = parts[0], parts[1], parts[2], parts[3]
        # Only use street if it has a house number — a bare street name (no leading digit)
        # can match a same-named place in a different state and produce a wrong result.
        if street and street[0].isdigit():
            params = {**base, 'street': street, 'city': city, 'state': state, 'postalcode': zipcode}
        else:
            params = {**base, 'city': city, 'state': state, 'postalcode': zipcode}
    elif len(parts) == 3:
        params = {**base, 'city': parts[0], 'state': parts[1], 'postalcode': parts[2]}
    else:
        params = {**base, 'q': address}

    resp = requests.get(
        'https://nominatim.openstreetmap.org/search',
        params=params,
        headers={'User-Agent': 'UniversalSpiralAirDeliveryApp/1.0'},
        timeout=5
    )
    results = resp.json()

    # Fall back to city+zip if the street-level search returns nothing
    if not results and 'street' in params:
        fallback = {**base, 'city': params['city'], 'state': params['state'], 'postalcode': params['postalcode']}
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params=fallback,
            headers={'User-Agent': 'UniversalSpiralAirDeliveryApp/1.0'},
            timeout=5
        )
        results = resp.json()

    if not results:
        return None
    coords = (float(results[0]['lat']), float(results[0]['lon']))
    _geocode_cache[address] = coords
    return coords


@app.route('/api/stop-to-stop')
def stop_to_stop():
    origin = request.args.get('origin', '').strip()
    dest = request.args.get('dest', '').strip()
    if not origin or not dest:
        return jsonify({'error': 'Missing origin or dest'}), 400
    try:
        origin_coords = geocode_address(origin)
        dest_coords = geocode_address(dest)
        if not origin_coords or not dest_coords:
            return jsonify({'error': 'Could not geocode address'}), 400
        olat, olng = origin_coords
        dlat, dlng = dest_coords
        osrm = requests.get(
            f'https://router.project-osrm.org/route/v1/driving/{olng},{olat};{dlng},{dlat}',
            params={'overview': 'false'},
            timeout=5
        )
        data = osrm.json()
        if data.get('code') != 'Ok':
            return jsonify({'error': 'Routing failed'}), 400
        minutes = round(data['routes'][0]['duration'] / 60)
        return jsonify({'minutes': minutes})
    except Exception as e:
        app.logger.error(f'Stop-to-stop error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/eta')
def get_eta():
    try:
        origin_lat = float(request.args['lat'])
        origin_lng = float(request.args['lng'])
        address = request.args.get('address', '').strip()
        if not address:
            return jsonify({'error': 'No address provided'}), 400

        coords = geocode_address(address)
        if not coords:
            return jsonify({'error': 'Could not locate address'}), 400

        dest_lat, dest_lng = coords
        osrm = requests.get(
            f'https://router.project-osrm.org/route/v1/driving/{origin_lng},{origin_lat};{dest_lng},{dest_lat}',
            params={'overview': 'false'},
            timeout=5
        )
        data = osrm.json()
        if data.get('code') != 'Ok':
            return jsonify({'error': 'Routing failed'}), 400

        minutes = round(data['routes'][0]['duration'] / 60)
        return jsonify({'minutes': minutes})
    except Exception as e:
        app.logger.error(f'ETA error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/order-lines')
def order_lines():
    so_nums = [s.strip() for s in request.args.get('so_nums', '').split(',') if s.strip()]
    if not so_nums:
        return jsonify({'orders': {}})
    placeholders = ','.join('?' * len(so_nums))
    query = f"""
        SELECT ORDER_NO, RTRIM(PART) AS part, RTRIM(DESCRIPTION) AS description,
               CAST(ROUND(QTY_ORDERED, 0) AS INTEGER) AS qty
        FROM V_ORDER_LINES
        WHERE ORDER_NO IN ({placeholders})
          AND PART NOT LIKE 'FRT%'
        ORDER BY ORDER_NO, RECORD_NO
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, so_nums)
        orders = {}
        for row in cursor.fetchall():
            key = str(row[0]).zfill(7)
            part = str(row[1] or '').strip()
            line = {
                'part': part,
                'description': str(row[2] or '').strip(),
                'qty': int(row[3]) if row[3] is not None else '',
                'sub_parts': []
            }
            orders.setdefault(key, []).append(line)

        # For CAM parts, fetch component list from GCG_7215_MAIN filtered by SO + part number
        cam_cache = {}  # (so_key, part) -> [sub_parts]
        for so_key, lines in orders.items():
            for line in lines:
                if line['part'].upper().startswith('CAM'):
                    cache_key = (so_key, line['part'])
                    if cache_key not in cam_cache:
                        cursor.execute(
                            "SELECT RTRIM(FITTING_NAME), QUANTITY FROM GCG_7215_MAIN"
                            " WHERE SO = ? AND RTRIM(COGS_PART_NUMBER) = ?",
                            (so_key, line['part'])
                        )
                        cam_cache[cache_key] = [
                            {'name': str(r[0] or '').strip(), 'qty': int(r[1]) if r[1] is not None else ''}
                            for r in cursor.fetchall()
                        ]
                    line['sub_parts'] = cam_cache[cache_key]

        conn.close()
        return jsonify({'orders': orders})
    except Exception as e:
        app.logger.error(f'Order lines error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/mark-delivered', methods=['POST'])
def mark_delivered():
    data = request.json or {}
    delivery_date = data.get('date', '').strip()
    driver = data.get('driver', '').strip()
    truck = data.get('truck', '').strip()
    delivery_order = data.get('delivery_order', '').strip()
    so_nums = data.get('so_nums', [])
    signature = data.get('signature', '')
    customer = data.get('customer', '').strip()
    if not all([delivery_date, driver, delivery_order]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO deliveries
                    (delivery_date, driver, truck, delivery_order, so_nums, delivered_at, signature, customer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (delivery_date, driver, truck, delivery_order,
                  json.dumps(so_nums), datetime.now().isoformat(), signature, customer))
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'Mark delivered error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    message = data.get('message', '').strip()
    sms_date = data.get('delivery_date', '').strip()
    sms_driver = data.get('driver', '').strip()
    sms_truck = data.get('truck', '').strip()
    sms_delivery_order = data.get('delivery_order', '').strip()
    if not phone or not message:
        return jsonify({'success': False, 'error': 'Missing phone or message'}), 400

    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN or not config.TWILIO_MESSAGING_SERVICE_SID:
        app.logger.warning(f'Twilio not configured — SMS not sent. To: {phone} | Message: {message}')
        return jsonify({'success': False, 'error': 'SMS provider not configured'}), 503

    to_number = phone
    dev_note = ''
    if config.DEV_SMS_OVERRIDE:
        to_number = config.DEV_SMS_OVERRIDE
        dev_note = f'[DEV — intended for {phone}] '

    try:
        from twilio.rest import Client
        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=dev_note + message,
            messaging_service_sid=config.TWILIO_MESSAGING_SERVICE_SID,
            to=to_number,
        )
        app.logger.info(f'SMS sent — To: {to_number} | Message: {dev_note}{message}')
        sent_at = datetime.now().isoformat()
        if sms_date and sms_driver and sms_truck and sms_delivery_order:
            try:
                with sqlite3.connect(DELIVERY_DB) as conn:
                    conn.execute(
                        'INSERT INTO sms_logs (delivery_date, driver, truck, delivery_order, sent_at) VALUES (?, ?, ?, ?, ?)',
                        (sms_date, sms_driver, sms_truck, sms_delivery_order, sent_at)
                    )
            except Exception as log_err:
                app.logger.error(f'SMS log error: {log_err}')
        return jsonify({'success': True, 'sent_at': format_time(sent_at)})
    except Exception as e:
        app.logger.error(f'SMS error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/navigate')
def navigate():
    so_raw = request.args.get('so_list', '[]')
    try:
        so_list = json.loads(so_raw)
    except Exception:
        so_list = []
    nav_date = request.args.get('date', '')
    nav_driver = request.args.get('driver', '')
    nav_truck = request.args.get('truck', '')
    nav_delivery_order = request.args.get('delivery_order', '')
    last_text_sent = get_last_text(nav_date, nav_driver, nav_truck, nav_delivery_order)
    return render_template('navigate.html',
        customer=request.args.get('customer', ''),
        address_street=request.args.get('street', ''),
        address_city=request.args.get('city', ''),
        contact=request.args.get('contact', ''),
        phone=request.args.get('phone', ''),
        notes=request.args.get('notes', ''),
        so_list=so_list,
        so_list_json=so_raw,
        maps_url=request.args.get('maps_url', '#'),
        display_address=request.args.get('address', ''),
        back_url=request.args.get('back', '/'),
        driver=nav_driver,
        date=nav_date,
        truck=nav_truck,
        delivery_order=nav_delivery_order,
        delivered=request.args.get('delivered', ''),
        company=config.COMPANY_NAME,
        last_text_sent=last_text_sent,
    )


@app.route('/api/unmark-delivered', methods=['POST'])
def unmark_delivered():
    data = request.json or {}
    delivery_date = data.get('date', '')
    driver = data.get('driver', '')
    truck = data.get('truck', '')
    delivery_order = data.get('delivery_order', '')
    if not all([delivery_date, driver, truck, delivery_order]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            conn.execute(
                'DELETE FROM deliveries WHERE delivery_date=? AND driver=? AND truck=? AND delivery_order=?',
                (delivery_date, driver, truck, delivery_order)
            )
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'Unmark delivered error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/deliveries')
def api_deliveries():
    """
    JSON delivery status for a given date. Merges ERP schedule with SQLite
    delivery records. Designed to be consumed by external dashboards as well
    as the built-in admin page.

    Query params:
      date  - ISO date string (default: today)

    Response:
      { "date": "...", "stops": [ { driver, truck, delivery_order, customer,
        address, so_nums, delivered, delivered_at, has_signature }, ... ] }
    """
    selected_date = request.args.get('date', date.today().isoformat())
    try:
        all_stops = fetch_stops(selected_date)
        grouped = group_stops_by_order(all_stops)

        with sqlite3.connect(DELIVERY_DB) as conn:
            dl_rows = conn.execute(
                '''SELECT driver, truck, delivery_order, so_nums,
                          delivered_at, customer,
                          CASE WHEN signature IS NOT NULL AND signature != '' THEN 1 ELSE 0 END
                   FROM deliveries WHERE delivery_date = ?''',
                (selected_date,)
            ).fetchall()

        dl_map = {}
        for row in dl_rows:
            key = (row[0], row[1], row[2])
            dl_map[key] = {
                'so_nums': json.loads(row[3] or '[]'),
                'delivered_at': format_time(row[4]),
                'customer': row[5] or '',
                'has_signature': bool(row[6]),
            }

        stops_out = []
        for stop in grouped:
            key = (stop['driver'], stop['truck'], stop['delivery_order'])
            dl = dl_map.get(key)
            stops_out.append({
                'driver':         stop['driver'],
                'truck':          stop['truck'],
                'delivery_order': stop['delivery_order'],
                'customer':       stop['customer'],
                'address':        stop['display_address'],
                'so_nums':        stop['so_list'],
                'delivered':      dl is not None,
                'delivered_at':   dl['delivered_at'] if dl else None,
                'has_signature':  dl['has_signature'] if dl else False,
            })

        return jsonify({'date': selected_date, 'stops': stops_out})
    except Exception as e:
        app.logger.error(f'api_deliveries error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/vapid-public-key')
def vapid_public_key():
    return jsonify({'public_key': config.VAPID_PUBLIC_KEY})


@app.route('/api/send-push', methods=['POST'])
def send_push():
    data = request.json or {}
    subscription = data.get('subscription')
    payload = data.get('payload', {})
    if not subscription or not config.VAPID_PRIVATE_KEY:
        return jsonify({'success': False, 'error': 'Push not configured'}), 503
    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=config.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f'mailto:{config.VAPID_EMAIL}'},
        )
        return jsonify({'success': True})
    except WebPushException as exc:
        app.logger.error(f'Push error: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500
    except Exception as exc:
        app.logger.error(f'Push error: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/signature')
def api_signature():
    delivery_date  = request.args.get('date', '')
    driver         = request.args.get('driver', '')
    truck          = request.args.get('truck', '')
    delivery_order = request.args.get('delivery_order', '')
    if not all([delivery_date, driver, truck, delivery_order]):
        return jsonify({'signature': ''}), 400
    try:
        with sqlite3.connect(DELIVERY_DB) as conn:
            row = conn.execute(
                'SELECT signature FROM deliveries WHERE delivery_date=? AND driver=? AND truck=? AND delivery_order=?',
                (delivery_date, driver, truck, delivery_order)
            ).fetchone()
        return jsonify({'signature': row[0] if row and row[0] else ''})
    except Exception as e:
        app.logger.error(f'api_signature error: {e}')
        return jsonify({'signature': ''}), 500


@app.route('/admin')
def admin():
    selected_date = request.args.get('date', date.today().isoformat())
    try:
        all_stops = fetch_stops(selected_date)
        grouped = group_stops_by_order(all_stops)

        with sqlite3.connect(DELIVERY_DB) as conn:
            dl_rows = conn.execute(
                '''SELECT driver, truck, delivery_order, delivered_at, customer,
                          CASE WHEN signature IS NOT NULL AND signature != '' THEN 1 ELSE 0 END
                   FROM deliveries WHERE delivery_date = ?''',
                (selected_date,)
            ).fetchall()

        dl_map = {}
        for row in dl_rows:
            key = (row[0], row[1], row[2])
            dl_map[key] = {
                'delivered_at': format_time(row[3]),
                'customer': row[4] or '',
                'has_signature': bool(row[5]),
            }

        for stop in grouped:
            key = (stop['driver'], stop['truck'], stop['delivery_order'])
            dl = dl_map.get(key)
            stop['delivered']     = dl is not None
            stop['delivered_at']  = dl['delivered_at'] if dl else ''
            stop['has_signature'] = dl['has_signature'] if dl else False

        by_driver = {}
        for stop in grouped:
            by_driver.setdefault(stop['driver'], []).append(stop)

        total           = len(grouped)
        delivered_count = sum(1 for s in grouped if s['delivered'])
        error = None
    except Exception as e:
        app.logger.error(f'admin error: {e}')
        by_driver = {}
        total = delivered_count = 0
        error = 'Could not load schedule data.'

    return render_template('admin.html',
                           selected_date=selected_date,
                           by_driver=by_driver,
                           total=total,
                           delivered_count=delivered_count,
                           error=error)


if __name__ == '__main__':
    cert = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cert.pem')
    key = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'key.pem')
    if os.path.exists(cert) and os.path.exists(key):
        from cheroot.wsgi import Server
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        server = Server(('0.0.0.0', 5002), app)
        server.ssl_adapter = BuiltinSSLAdapter(cert, key)
        server.start()
    else:
        app.run(host='0.0.0.0', port=5002, debug=False)
