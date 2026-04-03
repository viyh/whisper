document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('password').focus();
    init_clipboard();
    init_tooltip();

    // Form submit
    document.querySelector('form').addEventListener('submit', function(e) {
        get_data(e);
    });

    // Toggle password visibility
    document.getElementById('togglepw').addEventListener('click', function() {
        toggle_password_visibility();
    });
});
