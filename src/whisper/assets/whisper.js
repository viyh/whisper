// Whisper - Secure secret sharing
// Argon2id password hashing + AES-256-GCM via Web Crypto API.
// Stored-secret format is version-tagged so a future v3 can ship without
// breaking already-stored v2 data; currently only version 2 is supported.

const WHISPER_VERSION = 2;

// Argon2id parameters - read from server config via data attributes
// Falls back to defaults if not present in DOM
const ARGON2_HASH_LEN = 32;

function get_argon2_params() {
    var el = document.getElementById('app-config');
    return {
        time: el ? parseInt(el.dataset.argon2Time) || 5 : 5,
        mem: el ? parseInt(el.dataset.argon2Mem) || 131072 : 131072,
        par: el ? parseInt(el.dataset.argon2Par) || 1 : 1
    };
}

// --- Clipboard ---

function init_clipboard() {
    var clipboard = new ClipboardJS('.clipbtn', {
        text: function(trigger) {
            var target = document.querySelector(trigger.dataset.clipboardTarget);
            return target ? target.value : '';
        }
    });
    clipboard.on('success', function(e) {
        var btn = e.trigger;
        setTooltip(btn, 'Copied');
        hideTooltip(btn);
    });
    clipboard.on('error', function(e) {
        var btn = e.trigger;
        setTooltip(btn, 'Failed!');
        hideTooltip(btn);
    });
}

// --- Tooltips (Bootstrap 5 native) ---

function init_tooltip() {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function(el) {
        new bootstrap.Tooltip(el, { trigger: 'manual' });
    });
    var regenBtn = document.getElementById('regenbutton');
    if (regenBtn) {
        new bootstrap.Tooltip(regenBtn, { trigger: 'hover', placement: 'right' });
    }
}

function setTooltip(el, message) {
    var tooltip = bootstrap.Tooltip.getInstance(el);
    if (tooltip) {
        tooltip.hide();
        el.setAttribute('data-bs-original-title', message);
        tooltip.show();
    }
}

function hideTooltip(el) {
    setTimeout(function() {
        var tooltip = bootstrap.Tooltip.getInstance(el);
        if (tooltip) tooltip.hide();
    }, 1500);
}

// --- Password visibility toggle ---

function toggle_password_visibility() {
    var pw = document.getElementById('password');
    var eyeIcon = document.getElementById('eye-icon');
    var eyeSlashIcon = document.getElementById('eye-slash-icon');
    // Toggle via the `hidden` attribute rather than inline style writes so
    // the page stays compatible with a strict `style-src` CSP.
    if (pw.type === 'password') {
        pw.type = 'text';
        eyeIcon.hidden = true;
        eyeSlashIcon.hidden = false;
    } else {
        pw.type = 'password';
        eyeIcon.hidden = false;
        eyeSlashIcon.hidden = true;
    }
}

// --- Random password (rejection sampling, no modulo bias) ---

function random_pw(
    length = 32,
    wishlist = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz~!@-#$%*?+'
) {
    var maxValid = Math.floor(0x100000000 / wishlist.length) * wishlist.length;
    var result = [];
    while (result.length < length) {
        var values = crypto.getRandomValues(new Uint32Array(length * 2));
        for (var i = 0; i < values.length && result.length < length; i++) {
            if (values[i] < maxValid) {
                result.push(wishlist[values[i] % wishlist.length]);
            }
        }
    }
    return result.join('');
}

// --- File handling ---

function file_select() {
    var secret_file = document.getElementById('secret_file');
    var secret_text = document.getElementById('secret_text');
    if (secret_file.files.length == 1 && secret_file.files[0].name) {
        secret_text.disabled = true;
    } else {
        secret_text.disabled = false;
        secret_text.placeholder = 'Enter secret text here or select a file below';
    }
}

async function get_base64(file_input) {
    var file = file_input.files[0];
    var result_base64 = await new Promise(function(resolve) {
        var fr = new FileReader();
        fr.onload = function() { resolve(fr.result); };
        fr.readAsDataURL(file);
    });
    return 'filename:' + file.name + ',' + result_base64;
}

// --- V2 Crypto: Argon2id + AES-256-GCM via Web Crypto API ---

async function pw_hash_v2(password) {
    var params = get_argon2_params();
    var result = await argon2.hash({
        pass: password,
        salt: window.location.origin.repeat(2),
        time: params.time,
        mem: params.mem,
        parallelism: params.par,
        hashLen: ARGON2_HASH_LEN,
        type: argon2.ArgonType.Argon2id
    });
    return result.encoded;
}

async function derive_key_v2(password) {
    var encoder = new TextEncoder();
    var keyMaterial = await crypto.subtle.importKey(
        'raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits', 'deriveKey']
    );
    return await crypto.subtle.deriveKey(
        {
            name: 'PBKDF2',
            salt: encoder.encode(window.location.origin),
            iterations: 600000,
            hash: 'SHA-256'
        },
        keyMaterial,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt', 'decrypt']
    );
}

function uint8_to_base64(bytes) {
    var chunks = [];
    var chunkSize = 8192;
    for (var i = 0; i < bytes.length; i += chunkSize) {
        chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize)));
    }
    return btoa(chunks.join(''));
}

function base64_to_uint8(b64) {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

async function encrypt_v2(plaintext, password) {
    var key = await derive_key_v2(password);
    var iv = crypto.getRandomValues(new Uint8Array(12));
    var plaintextBytes = new TextEncoder().encode(plaintext);
    var ciphertext = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv },
        key,
        plaintextBytes
    );
    // Prepend IV to ciphertext, encode as base64
    var combined = new Uint8Array(iv.length + ciphertext.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(ciphertext), iv.length);
    return uint8_to_base64(combined);
}

async function decrypt_v2(ciphertext_b64, password) {
    var key = await derive_key_v2(password);
    var combined = base64_to_uint8(ciphertext_b64);
    var iv = combined.slice(0, 12);
    var ciphertext = combined.slice(12);
    var plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: iv },
        key,
        ciphertext
    );
    return new TextDecoder().decode(plaintext);
}

// --- API call (vanilla fetch) ---

async function api_call(method, data) {
    var response = await fetch(window.location.href, {
        method: method,
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify(data)
    });
    return await response.json();
}

// --- Create secret flow ---

async function send_new_link_data(encrypted, password, expiration) {
    var hashed = await pw_hash_v2(password);
    var api_data = {
        encrypted_data: encrypted,
        password: hashed,
        expiration: expiration,
        version: WHISPER_VERSION
    };
    document.getElementById('secret_link').value = 'Uploading data and generating link...';
    try {
        var response = await api_call('POST', api_data);
        if (response.id) {
            var secret_link = document.getElementById('secret_link');
            secret_link.value = location.origin + location.pathname + response.id;
            document.getElementById('copybutton').click();
        } else {
            document.getElementById('secret_link').value = response.result || 'Could not create link.';
        }
    } catch (e) {
        document.getElementById('secret_link').value = 'Could not create link.';
    }
}

async function new_link(event) {
    event.preventDefault();
    var password = document.getElementById('password').value;
    var secret_text = document.getElementById('secret_text').value;
    var secret_file = document.getElementById('secret_file');
    var expiration = document.getElementById('expiration').value;
    var secret_link = document.getElementById('secret_link');

    if (!secret_text && !secret_file.value) {
        secret_link.value = 'Please enter text or choose a file.';
        return;
    }

    secret_link.value = 'Encrypting, please wait...';

    var plaintext;
    if (secret_file && secret_file.value != '') {
        plaintext = await get_base64(secret_file);
    } else {
        plaintext = secret_text;
    }

    var encrypted = await encrypt_v2(plaintext, password);
    await send_new_link_data(encrypted, password, expiration);
}

// --- Retrieve secret flow ---

function dataURL_to_blob(file_mime, file_contents) {
    var ab = new ArrayBuffer(file_contents.length);
    var ia = new Uint8Array(ab);
    for (var i = 0; i < file_contents.length; i++) {
        ia[i] = file_contents.charCodeAt(i);
    }
    return new Blob([ab], { type: file_mime });
}

function download_secret_file(decrypted, file_name, file_mime) {
    var file_contents = atob(decrypted);
    var blob = dataURL_to_blob(file_mime, file_contents);
    var file_dl = document.createElement('a');
    file_dl.download = file_name;
    file_dl.href = window.URL.createObjectURL(blob);
    file_dl.click();
}

function display_secret_text(decrypted) {
    document.getElementById('decrypted_text').value = decrypted;
}

async function get_data(event) {
    event.preventDefault();
    var password = document.getElementById('password').value;
    var decrypted_text = document.getElementById('decrypted_text');
    decrypted_text.value = 'Downloading secret...';

    try {
        var hashed = await pw_hash_v2(password);
        var response = await api_call('POST', { password: hashed });

        if (!response.encrypted_data) {
            decrypted_text.value = response.result || 'Error retrieving secret.';
            return;
        }

        // Only version 2 is supported. Anything else indicates data written by
        // an incompatible build (e.g. a pre-0.2.0 v1 secret being read by a
        // post-v1-removal client). Surface an error rather than silently
        // falling through.
        if ((response.version || 0) !== WHISPER_VERSION) {
            decrypted_text.value = 'Unsupported secret format (version ' +
                response.version + '). Use the release/0.1.0_to_0.2.0 branch ' +
                'to decrypt legacy v1 secrets.';
            return;
        }

        var decrypted = await decrypt_v2(response.encrypted_data, password);

        var regex = /^filename:(.+?),data:(\w+\/[-+.\w]+);base64,/;
        var match = decrypted.substring(0, 100).match(regex);
        if (match) {
            download_secret_file(decrypted.replace(regex, ''), match[1], match[2]);
        } else {
            display_secret_text(decrypted);
            document.getElementById('copybutton').click();
        }
    } catch (e) {
        decrypted_text.value = 'Error decrypting secret. Wrong password?';
    }
}
