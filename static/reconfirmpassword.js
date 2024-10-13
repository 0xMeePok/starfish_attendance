function validatePassword() {
    var password = document.getElementById("password");
    var confirm_password = document.getElementById("confirm_password");
    var errorMessage = document.getElementById("error-message"); 

    // Clear previous error message
    errorMessage.style.display = 'none';
    errorMessage.textContent = '';

    if (password.value !== confirm_password.value) {
        errorMessage.textContent = "Passwords do not match."; 
        errorMessage.style.display = 'block'; // Show the error message
        return false;
    }
    return true;
}

document.getElementById('myForm').onsubmit = function(event) {
    event.preventDefault(); // Prevent the default form submission

    if (validatePassword()) {
        console.log("Form is valid! Now you can submit it via AJAX or other methods.");
        this.submit(); // Submit the form if validation passes
    } else {
        console.log("Form is invalid! Please correct the errors.");
    }
};
