// Whisper - Secure secret sharing
//
// Secret format v3. A share link is <base>#<token>: a random 22-character
// base58 token after the "#", which browsers never send to the server. From
// the token and the password, the browser derives:
//   - the secret ID: SHA-256 of the token. The server stores the secret
//     under it, so the server, its storage and its logs never see the token.
//   - Argon2id(password, salt = token), split with HKDF into:
//       - an AES-256-GCM key that encrypts the secret, and
//       - an auth token the server checks before returning the ciphertext.
// So opening a secret needs both the full link and the password, even for
// someone holding a copy of the server's storage and secret_key.

const WHISPER_VERSION = 3;

// base58: alphanumeric without the look-alikes 0, O, I and l, so links
// survive chat apps and Markdown, and can be read out or retyped.
// 22 characters = 128.9 random bits.
const TOKEN_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const TOKEN_LENGTH = 22;
const TOKEN_PATTERN = /^[1-9A-HJ-NP-Za-km-z]{22}/;

const ARGON2_HASH_LEN = 32;

// argon2-browser loads its WASM on first use. Use the SIMD build where the
// browser supports WebAssembly SIMD (all current browsers; roughly 1.3-2x
// faster), and the plain build otherwise. Both produce identical hashes.
// Files are found next to the argon2-browser script tag, so this works under
// any app_url_base.
var WASM_SIMD_PROBE = new Uint8Array([
    0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1,
    8, 0, 65, 0, 253, 15, 253, 98, 11
]);

function wasm_simd_supported() {
    try {
        return typeof WebAssembly === 'object' && WebAssembly.validate(WASM_SIMD_PROBE);
    } catch (e) {
        return false;
    }
}

(function configure_argon2() {
    var lib = document.querySelector('script[src*="argon2-browser"]');
    if (!lib) return;
    var dir = lib.src.replace(/lib\/argon2\.js(\?.*)?$/, 'dist/');
    window.whisperArgon2Build = wasm_simd_supported() ? 'simd' : 'plain';
    window.argon2WasmPath = dir + (window.whisperArgon2Build === 'simd' ? 'argon2-simd.wasm' : 'argon2.wasm');
    window.loadArgon2WasmModule = function() {
        return new Promise(function(resolve, reject) {
            var s = document.createElement('script');
            s.src = dir + 'argon2.js';
            s.onload = function() { resolve(window.Module); };
            s.onerror = reject;
            document.head.appendChild(s);
        });
    };
})();

// Argon2id parameters - read from server config via data attributes
// Falls back to defaults if not present in DOM
function get_argon2_params() {
    var el = document.getElementById('app-config');
    return {
        time: el ? parseInt(el.dataset.argon2Time) || 5 : 5,
        mem: el ? parseInt(el.dataset.argon2Mem) || 131072 : 131072,
        par: el ? parseInt(el.dataset.argon2Par) || 1 : 1
    };
}

// --- Clipboard ---
// Native async Clipboard API where available (all current browsers, on HTTPS
// or localhost), falling back to the older execCommand('copy') path that
// clipboard.js used, for older browsers and embedded webviews.

async function copy_text(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // e.g. permission denied or no user gesture: try the fallback
        }
    }
    return copy_text_fallback(text);
}

function copy_text_fallback(text) {
    var active = document.activeElement;
    var helper = document.createElement('textarea');
    helper.className = 'clip-helper';
    helper.setAttribute('readonly', '');
    helper.value = text;
    document.body.appendChild(helper);
    helper.select();
    helper.setSelectionRange(0, text.length); // iOS Safari
    var ok = false;
    try {
        ok = document.execCommand('copy');
    } catch (e) {
        ok = false;
    }
    document.body.removeChild(helper);
    if (active && active.focus) active.focus();
    return ok;
}

function init_clipboard() {
    document.querySelectorAll('.clipbtn').forEach(function(btn) {
        btn.addEventListener('click', async function(e) {
            var target = document.querySelector(btn.dataset.clipboardTarget);
            var ok = target ? await copy_text(target.value) : false;
            if (ok) {
                show_tip(btn, 'Copied!');
            } else {
                // the automatic copy of a new link can be refused
                // by the browser without a direct click; ask for one
                show_tip(btn, e.isTrusted ? 'Copy failed' : 'Click to copy');
            }
        });
    });
}

// --- Tooltips ---
// The bubble is pure CSS (see .tip in style.css); this only sets its text and
// shows it briefly. Works the same for mouse, touch and keyboard.

function show_tip(el, message, ms) {
    if (!el.dataset.tipDefault && el.dataset.tip) el.dataset.tipDefault = el.dataset.tip;
    el.dataset.tip = message;
    el.classList.add('tip-show');
    clearTimeout(el.tipTimer);
    el.tipTimer = setTimeout(function() {
        el.classList.remove('tip-show');
        if (el.dataset.tipDefault) el.dataset.tip = el.dataset.tipDefault;
    }, ms || 1500);
}

// --- Password visibility toggle ---

function toggle_password_visibility(button) {
    var pw = document.querySelector(button.dataset.target);
    var eyeIcon = button.querySelector('.bi-eye');
    var eyeSlashIcon = button.querySelector('.bi-eye-slash');
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

function max_file_size_kb() {
    var el = document.getElementById('app-config');
    return parseInt((el && el.dataset.maxFileSizeKb) || '100');
}

// Whether the chosen file is over max_data_size_kb
function file_too_large(file_input) {
    var file = file_input.files && file_input.files[0];
    return !!file && file.size / 1000 > max_file_size_kb();
}

async function get_base64(file_input) {
    var file = file_input.files[0];
    var result_base64 = await new Promise(function(resolve, reject) {
        var fr = new FileReader();
        fr.onload = function() { resolve(fr.result); };
        // e.g. the file was moved or deleted after it was chosen
        fr.onerror = function() { reject(fr.error); };
        fr.readAsDataURL(file);
    });
    return 'filename:' + file.name + ',' + result_base64;
}

// A received file's name without control characters or bidirectional
// overrides (U+202E can make "invoice<U+202E>fdp.exe" display as
// "invoiceexe.pdf")
var UNSAFE_NAME_CHARS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;

function safe_file_name(name) {
    return name.replace(UNSAFE_NAME_CHARS, '') || 'download';
}

// --- Link token ---

function new_token() {
    return random_pw(TOKEN_LENGTH, TOKEN_ALPHABET);
}

// The token from the current URL, or null if there isn't a complete one.
// Anything after the 22 characters (e.g. punctuation a chat app glued onto
// the link) is ignored.
function link_token() {
    var match = location.hash.slice(1).match(TOKEN_PATTERN);
    return match ? match[0] : null;
}

// The page's base path, e.g. "/" or "/whisper/"
function base_path() {
    return location.pathname.replace(/[^/]*$/, '');
}

// --- Crypto (v3): Argon2id + HKDF + AES-256-GCM, see the top of this file ---

// argon2-browser loads its WASM on first use, and after a failed load (e.g. a
// network error) it keeps failing until the page is reloaded
class Argon2Error extends Error {}
const ARGON2_FAILED = 'Could not load or run the encryption code. Reload the page and try again.';

function to_hex(buffer) {
    return Array.from(new Uint8Array(buffer), function(b) {
        return b.toString(16).padStart(2, '0');
    }).join('');
}

async function derive_keys(password, token) {
    var enc = new TextEncoder();
    // Web Crypto runs off the main thread, so this overlaps with Argon2
    var id = crypto.subtle.digest('SHA-256', enc.encode('whisper v3 id:' + token));
    var params = get_argon2_params();
    var result;
    try {
        result = await argon2.hash({
            pass: password,
            salt: token,
            time: params.time,
            mem: params.mem,
            parallelism: params.par,
            hashLen: ARGON2_HASH_LEN,
            type: argon2.ArgonType.Argon2id
        });
    } catch (e) {
        throw new Argon2Error(e && e.message);
    }
    var master = await crypto.subtle.importKey(
        'raw', result.hash, 'HKDF', false, ['deriveBits', 'deriveKey']
    );
    function hkdf(info) {
        return { name: 'HKDF', hash: 'SHA-256', salt: enc.encode('whisper v3'), info: enc.encode(info) };
    }
    var auth = await crypto.subtle.deriveBits(hkdf('auth'), master, 256);
    var key = await crypto.subtle.deriveKey(
        hkdf('encryption'), master, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']
    );
    return { id: to_hex(await id), auth: to_hex(auth), key: key };
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

// The ciphertext is bound to its ID (AES-GCM additional data), so it can't be
// passed off as a different secret.
async function encrypt_secret(plaintext, keys) {
    var enc = new TextEncoder();
    var iv = crypto.getRandomValues(new Uint8Array(12));
    var ciphertext = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv, additionalData: enc.encode(keys.id) },
        keys.key,
        enc.encode(plaintext)
    );
    // Prepend IV to ciphertext, encode as base64
    var combined = new Uint8Array(iv.length + ciphertext.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(ciphertext), iv.length);
    return uint8_to_base64(combined);
}

async function decrypt_secret(ciphertext_b64, keys) {
    var combined = base64_to_uint8(ciphertext_b64);
    var plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: combined.slice(0, 12), additionalData: new TextEncoder().encode(keys.id) },
        keys.key,
        combined.slice(12)
    );
    return new TextDecoder().decode(plaintext);
}

// --- API call (vanilla fetch) ---

function unexpected_response(status) {
    return { result: 'Unexpected response from the server (HTTP ' + status + '). Please try again.' };
}

// Whisper answers in JSON, errors included. Anything else (no connection, an
// HTML error page from a proxy in front of it, or an empty or cut-off body)
// becomes a { result } message.
async function api_post(path, data) {
    var response;
    try {
        response = await fetch(base_path() + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json; charset=utf-8' },
            body: JSON.stringify(data)
        });
    } catch (e) {
        return { result: 'Could not reach the server. Check your connection and try again.' };
    }
    var type = response.headers.get('Content-Type') || '';
    if (type.indexOf('application/json') === -1) {
        if (response.status === 413) {
            return { result: 'The secret is too large.' };
        }
        return unexpected_response(response.status);
    }
    try {
        return await response.json();
    } catch (e) {
        return unexpected_response(response.status);
    }
}

// --- Create secret flow ---

// true while a secret is being created: repeat submits are ignored, so a
// double click doesn't upload a second secret
var creating = false;

async function new_link(event) {
    event.preventDefault();
    if (creating) return;
    var password = document.getElementById('password').value;
    var secret_text = document.getElementById('secret_text').value;
    var secret_file = document.getElementById('secret_file');
    var expiration = document.getElementById('expiration').value;
    var secret_link = document.getElementById('secret_link');
    var create_button = document.getElementById('create_secret');

    if (!secret_text && !secret_file.value) {
        secret_link.value = 'Please enter text or choose a file.';
        return;
    }

    creating = true;
    create_button.disabled = true;
    secret_link.value = 'Encrypting, please wait...';

    try {
        var plaintext;
        if (secret_file && secret_file.value != '') {
            try {
                plaintext = await get_base64(secret_file);
            } catch (e) {
                secret_link.value = 'Could not read the file. Choose it again and retry.';
                return;
            }
        } else {
            plaintext = secret_text;
        }
        var token = new_token();
        var keys = await derive_keys(password, token);
        var encrypted = await encrypt_secret(plaintext, keys);
        secret_link.value = 'Uploading data and generating link...';
        var response = await api_post('', {
            id: keys.id,
            auth: keys.auth,
            encrypted_data: encrypted,
            expiration: expiration,
            version: WHISPER_VERSION
        });
        if (response.id === keys.id) {
            secret_link.value = location.origin + base_path() + '#' + token;
            document.getElementById('copybutton').click();
        } else {
            secret_link.value = response.result || 'Could not create link.';
        }
    } catch (e) {
        secret_link.value = e instanceof Argon2Error ? ARGON2_FAILED : 'Could not create link.';
    } finally {
        creating = false;
        create_button.disabled = file_too_large(secret_file);
    }
}

// --- Retrieve secret flow ---

// Always application/octet-stream, whatever type the sender's file had. A
// browser that ignores the download attribute (some in-app webviews) opens
// the file instead, and an HTML or SVG file would then run as a page on
// Whisper's origin.
function download_secret_file(file_base64, file_name) {
    var blob = new Blob([base64_to_uint8(file_base64)], { type: 'application/octet-stream' });
    var url = URL.createObjectURL(blob);
    var file_dl = document.createElement('a');
    file_dl.download = file_name;
    file_dl.href = url;
    file_dl.click();
    // revoking right away can cancel the download in some browsers
    setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
}

// A file secret is "filename:<name>," then the file's data URL. Office types
// alone are 70+ characters, and files of unknown type can have an empty one
// ("data:;base64,"). The type is only used to recognize a file.
var FILE_SECRET = /^filename:(.+?),data:([-+.\w]+\/[-+.\w]+)?;base64,/;

function show_secret(decrypted, output) {
    var match = decrypted.substring(0, 1024).match(FILE_SECRET);
    if (match) {
        var file_name = safe_file_name(match[1]);
        try {
            download_secret_file(decrypted.slice(match[0].length), file_name);
            output.value = 'Downloaded ' + file_name + '.';
            return;
        } catch (e) {
            // not base64 after all: text that only looks like a file
        }
    }
    // not copied automatically: clipboard managers and cross-device
    // clipboard sync would pick it up. The copy button is right there.
    output.value = decrypted;
}

async function get_data(event) {
    event.preventDefault();
    var retrieve_button = document.getElementById('retrieve_secret');
    // Disabled while a request is running, and for good once the secret is
    // open: its token has left the address bar, so another try would fail
    // and replace the secret on screen (a one-time secret can't be fetched
    // again)
    if (retrieve_button.disabled) return;
    var token = link_token();
    if (!token) return;
    var password = document.getElementById('retrieve_password').value;
    var decrypted_text = document.getElementById('decrypted_text');
    retrieve_button.disabled = true;
    decrypted_text.value = 'Decrypting, please wait...';
    var opened = false;

    try {
        var keys = await derive_keys(password, token);
        var response = await api_post('retrieve', { id: keys.id, auth: keys.auth });

        if (!response.encrypted_data) {
            decrypted_text.value = response.result || 'Error retrieving secret.';
            return;
        }
        if (response.version !== WHISPER_VERSION) {
            decrypted_text.value = 'Unsupported secret format (version ' + response.version + ').';
            return;
        }

        var decrypted = await decrypt_secret(response.encrypted_data, keys);
        opened = true;

        // the link has done its job: take the token out of the address bar
        // and browser history
        history.replaceState(null, '', location.pathname + location.search);
        show_secret(decrypted, decrypted_text);
    } catch (e) {
        decrypted_text.value = e instanceof Argon2Error ? ARGON2_FAILED : 'Error decrypting secret.';
    } finally {
        if (!opened) retrieve_button.disabled = false;
    }
}
