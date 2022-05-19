new ClipboardJS('.btn');
var web_url = '{{web_url}}';
var api_path = '/';

function encrypt(plaintext, password) {
    return CryptoJS.AES.encrypt(plaintext, password);
}

function decrypt(ciphertext, password) {
    return CryptoJS.AES.decrypt(ciphertext, password);
}

function pw_hash(password) {
    // Use known public salt for client-side hash.
    // This prevents the server administrator from ever knowing the
    // real password so they will be unable to decrypt the user's data.
    var salt = location.hostname;
    return CryptoJS.PBKDF2(password, salt, {
        keySize: 512 / 32,
        iterations: 10000
    }).toString(CryptoJS.enc.Base64);
}

async function getBase64(fileInput) {
    var file = fileInput.files[0];
    let result_base64 = await new Promise((resolve) => {
        let fileReader = new FileReader();
        fileReader.onload = (e) => resolve(fileReader.result);
        fileReader.readAsDataURL(file);
    });
    return 'filename:' + file.name + ',' + result_base64;
}

function send_new_link_data(encrypted, password, expiration, success, failure) {
    var api_data = {'encrypted_data': encrypted.toString(), 'password': pw_hash(password), 'expiration': expiration};
    document.getElementById('secret_link').value = 'Uploading data and generating link...';
    api_call(web_url + api_path, "POST", api_data, success, failure);
}

function new_link(event) {
    event.preventDefault();
    var password = document.getElementById('inputPassword').value;
    var inputText = document.getElementById('inputText').value;
    var inputFilename = document.getElementById('inputFilename');
    var expiration = document.getElementById('expiration').value;
    var encrypted = null;
    if (inputFilename && inputFilename.value != "") {
        getBase64(inputFilename).then(base64file => {
            encrypted = encrypt(base64file, password);
            send_new_link_data(encrypted, password, expiration, success, failure);
        });
    }
    else {
        encrypted = encrypt(inputText, password);
        send_new_link_data(encrypted, password, expiration, success, failure);
    }

    function success (response) {
        document.getElementById('secret_link').value = web_url + '/' + response['id'];
        return true;
    }
    function failure (response) {
        if ('result' in response) {
            document.getElementById('secret_link').value = response['result'];
        }
        else {
            document.getElementById('secret_link').value = 'Could not create link.';
        }
        return false;
    }

}

function dataURL_to_blob(file_mime, file_contents) {
    var ab = new ArrayBuffer(file_contents.length);
    var ia = new Uint8Array(ab);
    for (var i = 0; i < file_contents.length; i++) {
        ia[i] = file_contents.charCodeAt(i);
    }
    return blob = new Blob([ab], {type: file_mime});
}

function get_data(event) {
    event.preventDefault();
    var password = document.getElementById('inputPassword').value;
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
            var decrypted = decrypt(response['encrypted_data'].toString(), password).toString(CryptoJS.enc.Utf8);
            var regex = /^filename:(.+?),data:(\w+\/[-+.\w]+);base64,(.*)$/;
            var match = decrypted.substring(0,100).match(regex)
            if (match) {
                var file_name = match[1];
                var file_mime = match[2];
                var file_contents = atob(decrypted.split(',')[2]);
                console.log("File: ", file_name, file_mime);
                var blob = dataURL_to_blob(file_mime, file_contents);
                var file_dl = document.createElement('a');
                file_dl.download = file_name;
                file_dl.href = window.URL.createObjectURL(blob);
                file_dl.click();
            }
            else {
                var text = document.getElementById('decrypted_text')
                text.style.visibility = "visible";
                var label = document.getElementById('decrypted_text_label')
                label.style.visibility = "visible";
                console.log("Text: ", decrypted);
                document.getElementById('decrypted_text').value = decrypted;
            }
        }
    }
    var api_data = {'password': pw_hash(password)};
    document.getElementById('decrypted_text').value = "Downloading secret..."
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
