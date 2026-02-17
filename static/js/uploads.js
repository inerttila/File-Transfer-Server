(function () {
    var modal = document.getElementById("delete-modal");
    var cancelBtn = document.querySelector(".js-modal-cancel");
    var deleteBtn = document.querySelector(".js-modal-delete");
    var pendingForm = null;

    document.querySelectorAll(".js-delete-trigger").forEach(function (btn) {
        btn.addEventListener("click", function () {
            pendingForm = this.closest("form");
            if (pendingForm && modal) {
                var titleEl = modal.querySelector(".js-modal-title");
                if (titleEl) {
                    titleEl.textContent = pendingForm.getAttribute("data-confirm-message") || "Delete?";
                }
                modal.classList.add("is-open");
                modal.setAttribute("aria-hidden", "false");
            }
        });
    });

    function closeModal() {
        if (!modal) {
            return;
        }
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        pendingForm = null;
    }

    if (cancelBtn) {
        cancelBtn.addEventListener("click", closeModal);
    }
    if (deleteBtn) {
        deleteBtn.addEventListener("click", function () {
            if (pendingForm) {
                pendingForm.submit();
            }
            closeModal();
        });
    }
    if (modal) {
        modal.addEventListener("click", function (e) {
            if (e.target === modal) {
                closeModal();
            }
        });
    }
})();

(function () {
    document.querySelectorAll(".file-table-row").forEach(function (row) {
        row.addEventListener("click", function (ev) {
            if (ev.target.closest(".row-actions-table, .delete-form, .download-btn, .delete-btn")) {
                return;
            }
            var trigger = row.querySelector(".js-file-preview-trigger");
            if (trigger) {
                trigger.click();
            }
        });
    });
})();

(function () {
    var pinModal = document.getElementById("pin-modal");
    var pinTitle = pinModal && pinModal.querySelector(".js-pin-title");
    var pinDesc = pinModal && pinModal.querySelector(".js-pin-desc");
    var pinInput = document.getElementById("pin-modal-input");
    var pinModalNew = document.getElementById("pin-modal-new");
    var pinError = document.getElementById("pin-modal-error");
    var pinSetBtn = document.querySelector(".js-pin-set");
    var pinRemoveBtn = document.querySelector(".js-pin-remove");
    var pinRemoveWrap = document.getElementById("pin-remove-wrap");
    var pinCancelBtn = document.querySelector(".js-pin-cancel");
    var currentPinFolder = null;
    var currentPinFolderHasPin = false;

    function closePinModal() {
        if (pinModal) {
            pinModal.classList.remove("is-open");
            pinModal.setAttribute("aria-hidden", "true");
        }
        currentPinFolder = null;
        currentPinFolderHasPin = false;
        if (pinInput) {
            pinInput.value = "";
        }
        if (pinModalNew) {
            pinModalNew.value = "";
        }
        if (pinError) {
            pinError.style.display = "none";
            pinError.textContent = "";
        }
    }

    function showPinModal(folder, hasPin) {
        currentPinFolder = folder;
        currentPinFolderHasPin = hasPin === "true";
        if (pinTitle) {
            pinTitle.textContent = currentPinFolderHasPin ? "Change or remove PIN" : "Set a PIN to protect your folder";
        }
        if (pinDesc) {
            pinDesc.textContent = currentPinFolderHasPin
                ? "To remove protection, enter your current PIN below and click Remove PIN above. To change PIN, enter current and new PIN below and click Change PIN."
                : "Protect this folder so only people with the PIN can open it. PIN must be at least 4 characters.";
        }
        if (pinRemoveWrap) {
            pinRemoveWrap.style.display = currentPinFolderHasPin ? "flex" : "none";
        }
        if (pinSetBtn) {
            pinSetBtn.textContent = currentPinFolderHasPin ? "Change PIN" : "Set PIN";
        }
        if (pinInput) {
            pinInput.placeholder = currentPinFolderHasPin ? "Current PIN" : "Enter PIN";
            pinInput.value = "";
            pinInput.focus();
        }
        if (pinModalNew) {
            pinModalNew.style.display = "block";
            pinModalNew.value = "";
            pinModalNew.placeholder = currentPinFolderHasPin ? "New PIN" : "Confirm PIN";
        }
        if (pinModal) {
            pinModal.classList.add("is-open");
            pinModal.setAttribute("aria-hidden", "false");
        }
        if (pinError) {
            pinError.style.display = "none";
            pinError.textContent = "";
        }
    }

    document.querySelectorAll(".js-pin-menu").forEach(function (btn) {
        btn.addEventListener("click", function (e) {
            e.preventDefault();
            var folder = this.getAttribute("data-folder");
            var hasPin = this.getAttribute("data-has-pin") || "false";
            if (folder) {
                showPinModal(folder, hasPin);
            }
        });
    });

    if (pinCancelBtn) {
        pinCancelBtn.addEventListener("click", closePinModal);
    }
    if (pinModal) {
        pinModal.addEventListener("click", function (e) {
            if (e.target === pinModal) {
                closePinModal();
            }
        });
    }
    if (pinSetBtn) {
        pinSetBtn.addEventListener("click", function () {
            if (!currentPinFolder || !pinInput) {
                return;
            }
            var payload;
            if (currentPinFolderHasPin) {
                var currentPin = pinInput.value;
                var newPin = pinModalNew ? pinModalNew.value : "";
                if (newPin.length < 4) {
                    if (pinError) {
                        pinError.textContent = "New PIN must be at least 4 characters";
                        pinError.style.display = "block";
                    }
                    return;
                }
                payload = { pin: newPin, current_pin: currentPin };
            } else {
                var pin = pinInput.value;
                var confirmPin = pinModalNew ? pinModalNew.value : "";
                if (pin.length < 4) {
                    if (pinError) {
                        pinError.textContent = "PIN must be at least 4 characters";
                        pinError.style.display = "block";
                    }
                    return;
                }
                if (pin !== confirmPin) {
                    if (pinError) {
                        pinError.textContent = "PIN and Confirm PIN do not match";
                        pinError.style.display = "block";
                    }
                    return;
                }
                payload = { pin: pin };
            }

            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(currentPinFolder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    closePinModal();
                    window.location.reload();
                } else {
                    var r = null;
                    try { r = JSON.parse(xhr.responseText); } catch (z) {}
                    if (pinError) {
                        pinError.textContent = (r && r.error) || "Failed to set PIN";
                        pinError.style.display = "block";
                    }
                }
            };
            xhr.onerror = function () {
                if (pinError) {
                    pinError.textContent = "Network error";
                    pinError.style.display = "block";
                }
            };
            xhr.send(JSON.stringify(payload));
        });
    }

    var pinRemoveModal = document.getElementById("pin-remove-modal");
    var pinRemoveInput = document.getElementById("pin-remove-input");
    var pinRemoveError = document.getElementById("pin-remove-error");
    var pinRemoveCancelBtn = document.querySelector(".js-pin-remove-cancel");
    var pinRemoveConfirmBtn = document.querySelector(".js-pin-remove-confirm");

    function openRemovePinModal() {
        if (!currentPinFolder) {
            return;
        }
        if (pinRemoveInput) {
            pinRemoveInput.value = "";
            pinRemoveInput.focus();
        }
        if (pinRemoveError) {
            pinRemoveError.style.display = "none";
            pinRemoveError.textContent = "";
        }
        if (pinRemoveModal) {
            pinRemoveModal.classList.add("is-open");
            pinRemoveModal.setAttribute("aria-hidden", "false");
        }
    }

    function closeRemovePinModal() {
        if (pinRemoveModal) {
            pinRemoveModal.classList.remove("is-open");
            pinRemoveModal.setAttribute("aria-hidden", "true");
        }
        if (pinRemoveInput) {
            pinRemoveInput.value = "";
        }
        if (pinRemoveError) {
            pinRemoveError.style.display = "none";
            pinRemoveError.textContent = "";
        }
    }

    if (pinRemoveBtn) {
        pinRemoveBtn.addEventListener("click", openRemovePinModal);
    }
    if (pinRemoveCancelBtn) {
        pinRemoveCancelBtn.addEventListener("click", closeRemovePinModal);
    }
    if (pinRemoveModal) {
        pinRemoveModal.addEventListener("click", function (e) {
            if (e.target === pinRemoveModal) {
                closeRemovePinModal();
            }
        });
    }
    if (pinRemoveConfirmBtn) {
        pinRemoveConfirmBtn.addEventListener("click", function () {
            if (!currentPinFolder || !pinRemoveInput) {
                return;
            }
            var currentPin = pinRemoveInput.value;
            if (!currentPin || currentPin.length < 4) {
                if (pinRemoveError) {
                    pinRemoveError.textContent = "Please enter your current PIN";
                    pinRemoveError.style.display = "block";
                }
                return;
            }
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(currentPinFolder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    closeRemovePinModal();
                    closePinModal();
                    window.location.reload();
                } else {
                    var r = null;
                    try { r = JSON.parse(xhr.responseText); } catch (z) {}
                    if (pinRemoveError) {
                        pinRemoveError.textContent = (r && r.error) || "Failed to remove PIN";
                        pinRemoveError.style.display = "block";
                    }
                }
            };
            xhr.send(JSON.stringify({ remove: true, current_pin: currentPin }));
        });
    }
})();
