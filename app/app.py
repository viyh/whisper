#!/usr/bin/python

"""Whisper can be used to securely distribute credentials or other information
that is too sensitive to send via email or other plaintext methods."""

# pylint: disable=C0103,E0202

from __future__ import print_function
from random import random
from hashlib import sha1, pbkdf2_hmac
import binascii
import uuid
import time
import os
import decimal

import boto3
from botocore.exceptions import ClientError

import flask.json
from flask import Flask, request, jsonify, \
    send_from_directory, render_template, redirect, url_for
from werkzeug.routing import BaseConverter
from flask_cors import CORS

__version__ = '0.0.4'

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

def generate_hmac256(text, salt):
    """Generate HMAC256 hash"""
    text_bytes = bytes(text.encode('utf-8'))
    salt_bytes = bytes(salt.encode('utf-8'))
    salted_hmac = pbkdf2_hmac('sha256', text_bytes, salt_bytes, 100000)
    return binascii.hexlify(salted_hmac).decode('utf-8')

def get_ssha(sha):
    """Get a salted SHA from a regular SHA"""
    salt = uuid.uuid4().hex
    salted_hash = generate_hmac256(sha + secret_key, salt)
    return salt + salted_hash

def check_sha(sha, ssha):
    """Check if a regular SHA matches the stored salted SHA"""
    salt = ssha[:32]
    salted_hash = generate_hmac256(sha + secret_key, salt)
    return salted_hash == ssha[32:]

def check_item(item):
    """Check that the item has all the required keys"""
    keys = ['id', 'encrypted_data', 'created_date', 'expired_date', 'hash']
    return all(key in item for key in keys)

def get_dynamodb_item(data_id):
    """Retrieve an existing item"""
    try:
        dynamo_response = table.get_item(Key={'id': data_id})
        item = dynamo_response['Item']
        if not check_item(item):
            item = False
    except (ClientError, KeyError):
        item = False
    return item

def check_get_request():
    """Check that the request for an existing item has the necessary data"""
    return request.json and 'hash' in request.json

def check_new_request():
    """Check that the request for a new item has necessary data"""
    keys = ['encrypted_data', 'expiration', 'hash']
    return request.json or not all(key in request.json for key in keys)

def get_data_id():
    """Create a new item ID"""
    return sha1(str(random()).encode('utf-8')).hexdigest()

def create_new_item():
    """Create new item in DynamoDB."""
    new_data = {
        'id': get_data_id(),
        'encrypted_data': request.json['encrypted_data'],
        'created_date': int(time.time()),
        'expired_date': get_expired_date(request.json['expiration']),
        'hash': get_ssha(request.json['hash'])
    }
    table.put_item(Item=new_data)
    return new_data

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

@app.route('/whisper/api/v1.0/get/<data_id>', methods=['POST', 'OPTIONS'])
def api_get(data_id):
    """Retrieve encrypted data."""
    delete_expired()
    item = get_dynamodb_item(data_id)
    if not check_get_request() or not item or not check_sha(request.json['hash'], item['hash']):
        return jsonify({'result': 'No such id.'})
    elif one_time_item(item):
        table.delete_item(Key={'id': data_id})
    return jsonify(item)

@app.route('/whisper/api/v1.0/new', methods=['POST', 'OPTIONS'])
def api_new():
    """Create new encrypted item."""
    if not check_new_request():
        return jsonify({'result': 'Bad request.'})
    new_data = create_new_item()
    return jsonify(new_data)

@app.route('/<path:dummy>')
def fallback(dummy):
    """Redirect to index for all other requests."""
    return redirect(url_for('index'))

dynamodb_tablename = os.getenv('DYNAMODB_TABLENAME', 'whisper')
web_url = os.getenv('WEB_URL', 'http://localhost:8000')
secret_key = os.getenv('SECRET_KEY', 'aPdbh;/5G^|n43[Jpb~">c*|)xh8L0')
debug = True if os.getenv('DEBUG', 'False') in ['True', 'true', 'y' 'yes' 'on'] else False

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(dynamodb_tablename)
if debug:
    print(table.creation_date_time)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=debug)
