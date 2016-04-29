import sys, os, datetime, hashlib, hmac, urllib2, json

ENDPOINT = 'search-qa-nexus-cxr4m5dbpyd6pnzqs4lqlks53y.eu-west-1.es.amazonaws.com'


def sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def getSignatureKey(key, dateStamp, regionName, serviceName):
    kDate = sign(('AWS4' + key).encode('utf-8'), dateStamp)
    kRegion = sign(kDate, regionName)
    kService = sign(kRegion, serviceName)
    kSigning = sign(kService, 'aws4_request')
    return kSigning


def get_signature(method, canonical_uri):
    region = 'eu-west-1'
    service = 'es'
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    session_key = os.environ.get('AWS_SESSION_TOKEN')
    t = datetime.datetime.utcnow()
    amzdate = t.strftime('%Y%m%dT%H%M%SZ')
    datestamp = t.strftime('%Y%m%d')
    canonical_querystring = ''
    canonical_headers = 'host:' + ENDPOINT + '\nx-amz-date:' + amzdate + '\nx-amz-security-token:' + session_key + "\n"
    signed_headers = 'host;x-amz-date;x-amz-security-token'
    payload_hash = hashlib.sha256('').hexdigest()
    canonical_request = method + '\n' + canonical_uri + '\n' + canonical_querystring + '\n' + canonical_headers + '\n' + signed_headers + '\n' + payload_hash
    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = datestamp + '/' + region + '/' + service + '/' + 'aws4_request'
    string_to_sign = algorithm + '\n' + amzdate + '\n' + credential_scope + '\n' + hashlib.sha256(
        canonical_request).hexdigest()
    signing_key = getSignatureKey(secret_key, datestamp, region, service)
    signature = hmac.new(signing_key, (string_to_sign).encode('utf-8'), hashlib.sha256).hexdigest()
    authorization_header = algorithm + ' ' + 'Credential=' + access_key + '/' + credential_scope + ', ' + 'SignedHeaders=' + signed_headers + ', ' + 'Signature=' + signature
    headers = {'x-amz-date': amzdate, 'x-amz-security-token': session_key, 'Authorization': authorization_header}
    request_url = 'https://' + ENDPOINT + canonical_uri + '?' + canonical_querystring

    return {'url': request_url, 'headers': headers}


def lambda_handler(event, context):
    INDEXPREFIX = 'cwl-'
    TOLEAVE = 20

    response = json.loads(get_index_list())
    indexes = []
    for index in response:
        if index.startswith(INDEXPREFIX):
            indexes.append(index)

    indexes.sort(reverse=True)
    to_remove = indexes[TOLEAVE:]
    for index in to_remove:
        print("Removing " + index)
        delete_index(index)


def delete_index(index):
    info = get_signature('DELETE', '/' + index)

    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request(info['url'], headers=info['headers'])
    request.get_method = lambda: 'DELETE'

    r = opener.open(request)
    if r.getcode() != 200:
        raise Exception("Non 200 response when calling, got: " + str(r.getcode()))


def get_index_list():
    info = get_signature('GET', '/_aliases')

    request = urllib2.Request(info['url'], headers=info['headers'])
    r = urllib2.urlopen(request)
    if r.getcode() != 200:
        raise Exception("Non 200 response when calling, got: " + str(r.getcode()))

    return r.read()


if __name__ == '__main__':
    lambda_handler(None, None)
