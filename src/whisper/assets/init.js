// One page for both: create a secret, or open one when the URL has a #token.

function init_create_view() {
    document.getElementById('secret_text').focus();
    document.getElementById('password').value = random_pw();

    document.getElementById('create_form').addEventListener('submit', function(e) {
        new_link(e);
    });

    // File selection
    document.getElementById('secret_file').addEventListener('change', function() {
        file_select();
        // while a secret is being created, new_link sets both when it's done
        if (creating) return;
        var secretLink = document.getElementById('secret_link');
        var createSecret = document.getElementById('create_secret');
        if (file_too_large(this)) {
            createSecret.disabled = true;
            secretLink.value = 'Maximum file size is ' + max_file_size_kb() + ' KB.';
        } else {
            // including Cancel in the file picker, which can leave no file
            createSecret.disabled = false;
            secretLink.value = secretLink.defaultValue;
        }
    });

    // Password field and secret link - select all on click
    ['password', 'secret_link'].forEach(function(id) {
        document.getElementById(id).addEventListener('click', function() {
            this.setSelectionRange(0, this.value.length);
        });
    });

    document.getElementById('regenbutton').addEventListener('click', function() {
        document.getElementById('password').value = random_pw();
    });
}

function init_retrieve_view() {
    document.getElementById('create_view').hidden = true;
    document.getElementById('retrieve_view').hidden = false;

    if (!link_token()) {
        document.getElementById('decrypted_text').value =
            'This link is incomplete. Make sure you have the whole link, including everything after the #.';
        document.getElementById('retrieve_secret').disabled = true;
        return;
    }

    document.getElementById('retrieve_password').focus();
    document.getElementById('retrieve_form').addEventListener('submit', function(e) {
        get_data(e);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // Web Crypto only exists on secure pages (HTTPS, or localhost): say so
    // before anyone types a secret
    if (!window.isSecureContext || !window.crypto || !window.crypto.subtle) {
        document.getElementById('insecure_notice').hidden = false;
    }
    init_clipboard();
    document.querySelectorAll('.pwtoggle').forEach(function(button) {
        button.addEventListener('click', function() {
            toggle_password_visibility(button);
        });
    });

    // Opening another link in this tab only changes the #token, which doesn't
    // reload the page: reload so the right view and token are used.
    window.addEventListener('hashchange', function() {
        location.reload();
    });

    if (location.hash.length > 1) {
        init_retrieve_view();
    } else {
        init_create_view();
    }
});
