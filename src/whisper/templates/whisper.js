new ClipboardJS('.btn');
var web_url = '{{web_url}}';
var api_path = '/';

function encrypt(plaintext, password) {
    return CryptoJS.AES.encrypt(plaintext, password);
}

function decrypt(ciphertext, password) {
    return CryptoJS.AES.decrypt(ciphertext, password);
}

function new_link(event) {
    event.preventDefault();
    var password = document.getElementById('inputPassword').value;
    // var sha256 = get_ssha256(password);
    var plaintext = document.getElementById('inputText').value
    var expiration = document.getElementById('expiration').value;
    var encrypted = encrypt(plaintext, password);
    function success (response) {
        document.getElementById('secret_link').value = web_url + '/' + response['id'];
        return true;
    }
    function failure (response) {
        document.getElementById('secret_link').value = 'Could not create link.';
        return false;
    }
    var api_data = {'encrypted_data': encrypted.toString(), 'password': password, 'expiration': expiration};
    document.getElementById('secret_link').value = 'Generating link...';
    api_call(web_url + api_path, "POST", api_data, success, failure);
}

function get_data(event) {
    event.preventDefault();
    var password = document.getElementById('inputPassword').value;
    // var sha256 = get_ssha256(password);
    var secret_id = document.getElementById('secret_id').value;
    function failure (response) {
        document.getElementById('decrypted_text').value = response["result"];
        return false;
    }
    function success (response) {
        if (!('encrypted_data' in response)) {
            document.getElementById('decrypted_text').value = response["result"];
        }
        else {
            var decrypted = decrypt(response['encrypted_data'].toString(), password);
            document.getElementById('decrypted_text').value = decrypted.toString(CryptoJS.enc.Utf8);
        }
    }
    var api_data = {'password': password};
    api_call(web_url + api_path + secret_id, "POST", api_data, success, failure);
}

function api_call(url, type, api_data, success_callback, failure_callback) {
    $.ajax({
        url: url,
        type: type,
        processData: false,
        contentType: 'application/json; charset=utf-8',
        data: JSON.stringify(api_data),
        dataType: 'json',
        async: true,
        complete: function (xhr, textStatus) {
            response = $.parseJSON(xhr.responseText);
            if (textStatus != 'success' && failure_callback) {
                failure_callback(response);
            }
            else if (success_callback) {
                success_callback(response);
            }
        }
    });
}
