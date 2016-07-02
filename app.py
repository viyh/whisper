#!/usr/bin/python

"""Whisper can be used to securely distribute credentials or other information
that is too sensitive to send via email or other plaintext methods."""

# pylint: disable=C0103,E0202

from __future__ import print_function
from random import random
from hashlib import sha1
import time
import os
import decimal

import boto3

import flask.json
from flask import Flask, request, jsonify, \
    send_from_directory, render_template, redirect, url_for
from werkzeug.routing import BaseConverter
from flask_cors import CORS

__version__ = '0.0.3'

class MyJSONEncoder(flask.json.JSONEncoder):
    """JSON encoder for DynamoDB items to deal with decimal objects."""
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return int(obj)
        return super(MyJSONEncoder, self).default(obj)

class RegexConverter(BaseConverter):
    """Regex converter for parsing URL endpoints."""
    def __init__(self, url_map, *items):
        super(RegexConverter, self).__init__(url_map)
        self.regex = items[0]

app = Flask(__name__)
CORS(app)

app.url_map.converters['regex'] = RegexConverter
app.json_encoder = MyJSONEncoder

def get_expired_date(expiration):
    """Get epoch seconds of expiration date."""
    now = int(time.time())
    if expiration == '1 hour':
        return now + 3600
    elif expiration == '1 day':
        return now + 86400
    elif expiration == '1 week':
        return now + 86400 * 7
    else:
        return -1

def one_time_item(item):
    """Check if item is one time use."""
    return item['expired_date'] == -1

def expired_item(item):
    """Check if item is expired."""
    now = int(time.time())
    return (not one_time_item(item) and now >= item['expired_date']) or \
        now - item['created_date'] >= 86400 * 30

def delete_expired():
    """Delete expired items."""
    response = table.scan()
    if not 'Items' in response:
        return True
    for item in response['Items']:
        if expired_item(item):
            if debug:
                print("Deleting id: " + item['id'])
            table.delete_item(Key={'id': item['id']})
    return True

@app.route('/')
def index():
    """Index page."""
    return render_template('index.html', version=__version__)

@app.route('/js/whisper.js')
def send_whisperjs():
    """Serve js files."""
    return render_template('whisper.js', web_url=web_url)

@app.route('/js/<path:path>')
def send_js(path):
    """Serve js files."""
    return send_from_directory('js', path)

@app.route('/assets/<path:path>')
def send_assets(path):
    """Serve asset files."""
    return send_from_directory('assets', path)

@app.route('/<regex("[a-z0-9]{40,}"):data_id>')
def get_data(data_id):
    """Get data form."""
    response = table.get_item(Key={'id': data_id})
    if not 'Item' in response:
        return render_template('show.html', version=__version__, data_id=None, result='No such id.')
    else:
        return render_template('show.html', version=__version__, data_id=data_id)

@app.route('/whisper/api/v1.0/get/<data_id>', methods=['POST', 'GET', 'OPTIONS'])
def api_get(data_id):
    """Retrieve encrypted data."""
    delete_expired()
    response = table.get_item(Key={'id': data_id})
    if not response or not 'Item' in response:
        return jsonify({'result': 'No such id.'})
    item = response['Item']
    if one_time_item(item):
        table.delete_item(Key={'id': data_id})
    elif expired_item(item):
        table.delete_item(Key={'id': data_id})
        return jsonify({'result': "No such id."})
    return jsonify(item)

@app.route('/whisper/api/v1.0/new', methods=['POST', 'OPTIONS'])
def api_new():
    """Create new encrypted item."""
    if not request.json or not 'encrypted_data' in request.json or not 'expiration' in request.json:
        return 'False'
    random_string = sha1(str(random()).encode('utf-8')).hexdigest()
    new_data = {
        'id': random_string,
        'encrypted_data': request.json['encrypted_data'],
        'created_date': int(time.time()),
        'expired_date': get_expired_date(request.json['expiration'])
    }
    table.put_item(Item=new_data)
    return jsonify(new_data)

@app.route('/<path:dummy>')
def fallback(dummy):
    """Redirect to index for all other requests."""
    return redirect(url_for('index'))

if __name__ == '__main__':
    dynamodb_tablename = os.getenv('DYNAMODB_TABLENAME', 'whisper')
    web_url = os.getenv('WEB_URL', 'http://localhost:5000')
    web_port = int(os.getenv('WEB_PORT', '5000'))
    debug = True if os.getenv('DEBUG', 'False') in ['True', 'true', 'y' 'yes' 'on'] else False

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(dynamodb_tablename)
    if debug:
        print(table.creation_date_time)

    app.run(host='0.0.0.0', port=web_port, debug=debug)
