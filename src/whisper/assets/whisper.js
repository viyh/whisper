// AES Encrypt plaintext using password
function encrypt(plaintext, password) {
    return CryptoJS.AES.encrypt(plaintext, password);
}

// AES Decrypt plaintext using password
function decrypt(ciphertext, password) {
    return CryptoJS.AES.decrypt(ciphertext, password);
}

// Use known public salt for client-side hash (website URL * 4).
// This prevents the server administrator from ever knowing the
// real password so they will be unable to decrypt the user's data
// yet makes it predictable to generate again. The password hash is
// re-salted/hashed on the server-side with bcrypt for storage to
// prevent brute force attacks if the hash is stolen.
function pw_hash(password) {
    let salt = location.origin.repeat(4);
    return CryptoJS.PBKDF2(password, salt, {
        keySize: 512 / 32,
        iterations: 10000
    }).toString(CryptoJS.enc.Base64);
}

// Generate dataURL base64 data from file element
// Append "filename:<file_name>," to the data URL so that
// the filename can be retrieved upon decryption and no data
// leakage happens while the secret is stored.
async function get_base64(file_input) {
    let file = file_input.files[0];
    let result_base64 = await new Promise((resolve) => {
        let fr = new FileReader();
        fr.onload = (e) => resolve(fr.result);
        fr.readAsDataURL(file);
    });
    return 'filename:' + file.name + ',' + result_base64;
}

// Send API request
function send_new_link_data(encrypted, password, expiration, success, failure) {
    let api_data = {'encrypted_data': encrypted.toString(), 'password': pw_hash(password), 'expiration': expiration};
    document.getElementById('secret_link').value = 'Uploading data and generating link...';
    api_call("POST", api_data, success, failure);
}

// Generate a new secret link
function new_link(event) {
    event.preventDefault();
    let password = document.getElementById('password').value;
    let secret_text = document.getElementById('secret_text').value;
    let secret_filename = document.getElementById('secret_filename');
    let expiration = document.getElementById('expiration').value;
    let secret_link = document.getElementById('secret_link');
    let encrypted = null;
    if (secret_filename && secret_filename.value != "") {
        get_base64(secret_filename).then(base64_file => {
            encrypted = encrypt(base64_file, password);
            send_new_link_data(encrypted, password, expiration, success, failure);
        });
    }
    else {
        encrypted = encrypt(secret_text, password);
        send_new_link_data(encrypted, password, expiration, success, failure);
    }

    function success (response) {
        secret_link.value = location.origin + '/' + response['id'];
    }
    function failure (response) {
        if ('result' in response) {
            secret_link.value = response['result'];
        }
        else {
            secret_link.value = 'Could not create link.';
        }
    }

}

// Convery dataURL to binary Blob
function dataURL_to_blob(file_mime, file_contents) {
    let ab = new ArrayBuffer(file_contents.length);
    let ia = new Uint8Array(ab);
    for (let i = 0; i < file_contents.length; i++) {
        ia[i] = file_contents.charCodeAt(i);
    }
    return blob = new Blob([ab], {type: file_mime});
}

// Download decrypted secret file
function download_secret_file(decrypted, file_name, file_mime) {
    let file_contents = atob(decrypted.split(',')[2]);
    let blob = dataURL_to_blob(file_mime, file_contents);
    let file_dl = document.createElement('a');
    file_dl.download = file_name;
    file_dl.href = window.URL.createObjectURL(blob);
    file_dl.click();
}

// Display decrypted secret text
function display_secret_text(decrypted) {
    let text = document.getElementById('decrypted_text')
    text.value = decrypted;
}

// Get the secret from the server and decrypt it
function get_data(event) {
    event.preventDefault();
    let password = document.getElementById('password').value;
    let decrypted_text = document.getElementById('decrypted_text');
    function failure (response) {
        decrypted_text.value = response["result"];
    }
    function success (response) {
        if (!('encrypted_data' in response)) {
            decrypted_text.value = response["result"];
        }
        else {
            let regex = /^filename:(.+?),data:(\w+\/[-+.\w]+);base64,(.*)$/;
            let decrypted = decrypt(
                response['encrypted_data'].toString(),
                password
            ).toString(CryptoJS.enc.Utf8);
            let match = decrypted.substring(0,100).match(regex)
            if (match) {
                download_secret_file(decrypted, match[1], match[2]);
            }
            else {
                display_secret_text(decrypted);
            }
        }
    }
    let api_data = {'password': pw_hash(password)};
    decrypted_text.value = "Downloading secret..."
    api_call("POST", api_data, success, failure);
}

// Make API call with payload
function api_call(type, api_data, success_callback, failure_callback) {
    $.ajax({
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
