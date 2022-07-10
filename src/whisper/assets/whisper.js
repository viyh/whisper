function init_clipboard() {
    // Clipboard
    var clipboard = new ClipboardJS('.clipbtn');
    clipboard.on('success', function(e) {
        var btn = $(e.trigger);
        setTooltip(btn, 'Copied');
        hideTooltip(btn);
    });
    clipboard.on('error', function(e) {
        var btn = $(e.trigger);
        setTooltip(btn, 'Failed!');
        hideTooltip(btn);
    });
}

function init_tooltip() {
    // Tooltip for copied text
    $('[id=copybutton]').tooltip({
        trigger: 'manual',
        placement: 'right'
    });
    $('[id=copypwbutton]').tooltip({
        trigger: 'manual',
        placement: 'right'
    });
    $('[id=regenbutton]').tooltip({
        trigger: 'hover',
        placement: 'right'
    });
}

function setTooltip(btn, message) {
    btn.tooltip('hide')
      .attr('data-original-title', message)
      .tooltip('show');
  }

  function hideTooltip(btn) {
    setTimeout(function() {
      btn.tooltip('hide');
    }, 1500);
  }

// Random password
function random_pw(
    length = 32,
    wishlist = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz~!@-#$%*?+'
) {
    return Array.from(crypto.getRandomValues(new Uint32Array(length)))
      .map((x) => wishlist[x % wishlist.length])
      .join('')
}

// Show filename in textbox
function file_select() {
    secret_file = document.getElementById('secret_file');
    secret_text = document.getElementById('secret_text');
    if (secret_file.files.length == 1 && secret_file.files[0].name) {
        secret_text.disabled = true;
        // secret_text.placeholder = 'File selected: ' + secret_file.files[0].name;
    }
    else {
        secret_text.disabled = false;
        secret_text.placeholder = 'Enter secret text here or select a file below';
    }
}

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
    let salt = btoa(location.origin.repeat(4));
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
    let secret_file = document.getElementById('secret_file');
    let expiration = document.getElementById('expiration').value;
    let secret_link = document.getElementById('secret_link');
    let encrypted = null;
    secret_link.value = 'Encrypting, please wait...';
    if (!secret_text && !secret_file.value) {
        secret_link.value = 'Please enter text or choose a file.';
    }
    else if (secret_file && secret_file.value != "") {
        get_base64(secret_file).then(base64_file => {
            encrypted = encrypt(base64_file, password);
            send_new_link_data(encrypted, password, expiration, success, failure);
        });
    }
    else {
        encrypted = encrypt(secret_text, password);
        send_new_link_data(encrypted, password, expiration, success, failure);
    }

    function success (response) {
        secret_link.value = location.origin + location.pathname + response['id'];
        document.getElementById('copybutton').click();
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
    let file_contents = atob(decrypted);
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
            let regex = /^filename:(.+?),data:(\w+\/[-+.\w]+);base64,/;
            let decrypted = decrypt(
                response['encrypted_data'].toString(),
                password
            ).toString(CryptoJS.enc.Utf8);
            let match = decrypted.substring(0,100).match(regex)
            if (match) {
                download_secret_file(decrypted.replace(regex, ""), match[1], match[2]);
            }
            else {
                display_secret_text(decrypted);
                document.getElementById('copybutton').click();
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
