document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('secret_text').focus();
    document.getElementById('password').value = random_pw();
    init_clipboard();
    init_tooltip();

    // Form submit
    document.getElementById('form').addEventListener('submit', function(e) {
        new_link(e);
    });

    // File selection
    document.getElementById('secret_file').addEventListener('change', function() {
        file_select();
        var fileSize = this.files[0].size / 1000;
        var maxFileSizeKb = parseInt(document.getElementById('app-config').dataset.maxFileSizeKb || '100');
        var secretLink = document.getElementById('secret_link');
        var createSecret = document.getElementById('create_secret');
        if (fileSize > maxFileSizeKb) {
            createSecret.disabled = true;
            secretLink.value = 'Maximum file size is ' + maxFileSizeKb + ' KB.';
        } else {
            createSecret.disabled = false;
            secretLink.value = secretLink.defaultValue;
        }
    });

    // Password field - select all on click
    document.getElementById('password').addEventListener('click', function() {
        this.setSelectionRange(0, this.value.length);
    });

    // Secret link - select all on click
    document.getElementById('secret_link').addEventListener('click', function() {
        this.setSelectionRange(0, this.value.length);
    });

    // Toggle password visibility
    document.getElementById('togglepw').addEventListener('click', function() {
        toggle_password_visibility();
    });

    // Regenerate password
    document.getElementById('regenbutton').addEventListener('click', function() {
        document.getElementById('password').value = random_pw();
    });
});
