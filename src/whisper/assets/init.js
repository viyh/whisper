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
        var maxFileSizeKb = parseInt(document.getElementById('app-config').dataset.maxFileSizeKb || '100');
        var secretLink = document.getElementById('secret_link');
        var createSecret = document.getElementById('create_secret');
        // Cancel in the file picker can leave no file selected
        if (!this.files || this.files.length === 0) {
            createSecret.disabled = false;
            secretLink.value = secretLink.defaultValue;
            return;
        }
        if (this.files[0].size / 1000 > maxFileSizeKb) {
            createSecret.disabled = true;
            secretLink.value = 'Maximum file size is ' + maxFileSizeKb + ' KB.';
        } else {
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
