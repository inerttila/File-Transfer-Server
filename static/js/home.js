function transit() {
    var body = document.getElementById("body");
    if (body) {
        body.style.visibility = "visible";
    }
    var bar = document.getElementById("progress-bar");
    if (bar) {
        bar.style.width = "0%";
    }
    var pct = document.getElementById("progress-pct");
    if (pct) {
        pct.textContent = "0%";
    }
    var label = document.getElementById("progress-label");
    if (label) {
        label.textContent = "Uploading...";
    }
}

(function () {
    var form = document.querySelector("form[method=post][enctype*=multipart]");
    if (!form) {
        return;
    }
    var bodyEl = document.body;
    if (!window.UPLOADER_FOLDER && bodyEl && bodyEl.dataset) {
        window.UPLOADER_FOLDER = bodyEl.dataset.uploaderFolder || null;
    }

    var fileInput = document.getElementById("k-upload");
    var folderInput = document.getElementById("k-upload-folder");
    var folderPanel = document.getElementById("upload-folder-panel");
    var dropzone = document.getElementById("upload-dropzone");
    var uploadBtn = document.getElementById("upload-action-btn");
    var listEl = document.getElementById("is");
    var selectedCount = document.getElementById("selected-count");
    var selectedFiles = [];
    var previewObjectUrls = [];
    var packingFolder = false;

    function clearPreviewUrls() {
        previewObjectUrls.forEach(function (url) {
            try { URL.revokeObjectURL(url); } catch (e) {}
        });
        previewObjectUrls = [];
    }

    function formatSize(bytes) {
        if (!bytes || bytes < 1024) {
            return (bytes || 0) + " B";
        }
        var kb = bytes / 1024;
        if (kb < 1024) {
            return kb.toFixed(1) + " KB";
        }
        var mb = kb / 1024;
        return mb.toFixed(1) + " MB";
    }

    function renderSelectedFiles() {
        clearPreviewUrls();
        if (listEl) {
            listEl.innerHTML = "";
        }
        if (selectedFiles.length === 0) {
            if (selectedCount) {
                selectedCount.textContent = "";
            }
            if (uploadBtn) {
                uploadBtn.setAttribute("disabled", "disabled");
            }
            return;
        }
        if (selectedCount) {
            if (packingFolder) {
                selectedCount.textContent = selectedCount.getAttribute("data-packing-msg") || "Packing folder…";
            } else {
                selectedCount.textContent = selectedFiles.length + " file(s) selected";
            }
        }
        if (uploadBtn) {
            if (packingFolder) {
                uploadBtn.setAttribute("disabled", "disabled");
            } else {
                uploadBtn.removeAttribute("disabled");
            }
        }
        if (listEl) {
            selectedFiles.forEach(function (file, index) {
                var li = document.createElement("li");
                var main = document.createElement("div");
                main.className = "selected-file-main";

                var thumb;
                if (file.type && file.type.indexOf("image/") === 0) {
                    thumb = document.createElement("img");
                    thumb.className = "selected-file-thumb";
                    var objectUrl = URL.createObjectURL(file);
                    previewObjectUrls.push(objectUrl);
                    thumb.src = objectUrl;
                    thumb.alt = file.name;
                } else {
                    thumb = document.createElement("div");
                    thumb.className = "selected-file-thumb selected-file-thumb-generic";
                    var ext = "";
                    var dotIdx = file.name.lastIndexOf(".");
                    if (dotIdx > -1 && dotIdx < file.name.length - 1) {
                        ext = file.name.slice(dotIdx + 1).slice(0, 4).toUpperCase();
                    }
                    thumb.textContent = ext || "FILE";
                }

                var meta = document.createElement("div");
                meta.className = "selected-file-meta";

                var nameSpan = document.createElement("span");
                nameSpan.className = "selected-file-name";
                nameSpan.innerText = uploadPathForFile(file);

                var sizeSpan = document.createElement("span");
                sizeSpan.className = "selected-file-size";
                sizeSpan.innerText = formatSize(file.size || 0);

                meta.appendChild(nameSpan);
                meta.appendChild(sizeSpan);
                main.appendChild(thumb);
                main.appendChild(meta);

                var removeBtn = document.createElement("button");
                removeBtn.type = "button";
                removeBtn.className = "selected-file-remove-btn";
                removeBtn.innerText = "x";
                removeBtn.setAttribute("aria-label", "Remove " + file.name);
                removeBtn.addEventListener("click", function () {
                    selectedFiles.splice(index, 1);
                    renderSelectedFiles();
                });

                li.appendChild(main);
                li.appendChild(removeBtn);
                listEl.appendChild(li);
            });
        }
    }

    function setSelectedFiles(fileList) {
        packingFolder = false;
        selectedFiles = Array.prototype.slice.call(fileList || []);
        if (fileInput) {
            fileInput.value = "";
        }
        if (folderInput) {
            folderInput.value = "";
        }
        renderSelectedFiles();
    }

    function uploadPathForFile(file) {
        return file.webkitRelativePath || file.name;
    }

    function setPackingStatus(message) {
        packingFolder = true;
        selectedFiles = [];
        if (selectedCount) {
            selectedCount.setAttribute("data-packing-msg", message);
            selectedCount.textContent = message;
        }
        if (uploadBtn) {
            uploadBtn.setAttribute("disabled", "disabled");
        }
        if (listEl) {
            listEl.innerHTML = "";
        }
    }

    function packFolderThenSelect(rawFiles) {
        if (!window.FolderZip || !FolderZip.isFolderFileList(rawFiles)) {
            setSelectedFiles(rawFiles);
            return;
        }
        var folderName = FolderZip.folderDisplayName(rawFiles);
        var total = rawFiles.length;
        setPackingStatus("Packing \"" + folderName + "\" (0/" + total + ")…");
        FolderZip.zipFolderFiles(rawFiles, function (done, tot) {
            setPackingStatus("Packing \"" + folderName + "\" (" + done + "/" + tot + ")…");
        })
            .then(function (zipFile) {
                packingFolder = false;
                if (selectedCount) {
                    selectedCount.removeAttribute("data-packing-msg");
                }
                setSelectedFiles([zipFile]);
                if (selectedCount) {
                    selectedCount.textContent =
                        "Folder packed as " + zipFile.name + " (" + formatSize(zipFile.size) + ")";
                }
            })
            .catch(function () {
                packingFolder = false;
                if (selectedCount) {
                    selectedCount.removeAttribute("data-packing-msg");
                    selectedCount.textContent = "Could not pack folder. Try again or upload a .zip file.";
                }
                if (uploadBtn) {
                    uploadBtn.setAttribute("disabled", "disabled");
                }
            });
    }

    if (fileInput) {
        fileInput.addEventListener("change", function () {
            setSelectedFiles(fileInput.files);
        });
    }
    if (folderInput) {
        folderInput.addEventListener("change", function () {
            var files = Array.prototype.slice.call(folderInput.files || []);
            if (!files.length) {
                return;
            }
            packFolderThenSelect(files);
        });
    }

    function openFolderPicker(ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        if (folderInput) {
            folderInput.click();
        }
    }

    if (folderPanel && folderInput) {
        folderPanel.addEventListener("click", openFolderPicker);
        folderPanel.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" || ev.key === " ") {
                openFolderPicker(ev);
            }
        });
    }

    function attachRelativePath(file, path) {
        try {
            Object.defineProperty(file, "webkitRelativePath", {
                value: path,
                configurable: true,
            });
        } catch (e) {
            file.webkitRelativePath = path;
        }
    }

    function readAllDirectoryEntries(reader) {
        return new Promise(function (resolve, reject) {
            var all = [];
            function readBatch() {
                reader.readEntries(function (entries) {
                    if (!entries.length) {
                        resolve(all);
                        return;
                    }
                    all = all.concat(Array.prototype.slice.call(entries));
                    readBatch();
                }, reject);
            }
            readBatch();
        });
    }

    function collectFilesFromEntry(entry, prefix) {
        if (entry.isFile) {
            return new Promise(function (resolve, reject) {
                entry.file(function (file) {
                    attachRelativePath(file, prefix + file.name);
                    resolve([file]);
                }, reject);
            });
        }
        if (entry.isDirectory) {
            var reader = entry.createReader();
            var dirPrefix = prefix + entry.name + "/";
            return readAllDirectoryEntries(reader).then(function (children) {
                return Promise.all(children.map(function (child) {
                    return collectFilesFromEntry(child, dirPrefix);
                })).then(function (groups) {
                    return [].concat.apply([], groups);
                });
            });
        }
        return Promise.resolve([]);
    }

    function collectFromDataTransfer(dataTransfer) {
        return new Promise(function (resolve) {
            if (!dataTransfer) {
                resolve([]);
                return;
            }
            if (
                dataTransfer.items &&
                dataTransfer.items.length &&
                typeof dataTransfer.items[0].webkitGetAsEntry === "function"
            ) {
                var roots = [];
                Array.prototype.forEach.call(dataTransfer.items, function (item) {
                    var entry = item.webkitGetAsEntry();
                    if (entry) {
                        roots.push(entry);
                    }
                });
                if (!roots.length) {
                    resolve(Array.prototype.slice.call(dataTransfer.files || []));
                    return;
                }
                Promise.all(roots.map(function (entry) {
                    return collectFilesFromEntry(entry, "");
                }))
                    .then(function (groups) {
                        var files = [].concat.apply([], groups);
                        if (files.length) {
                            resolve(files);
                            return;
                        }
                        resolve(Array.prototype.slice.call(dataTransfer.files || []));
                    })
                    .catch(function () {
                        resolve(Array.prototype.slice.call(dataTransfer.files || []));
                    });
                return;
            }
            resolve(Array.prototype.slice.call(dataTransfer.files || []));
        });
    }

    function handleFileDrop(dataTransfer) {
        collectFromDataTransfer(dataTransfer).then(function (files) {
            if (!files.length) {
                return;
            }
            if (window.FolderZip && FolderZip.isFolderFileList(files)) {
                packFolderThenSelect(files);
                return;
            }
            setSelectedFiles(files);
        });
    }

    function handleFolderDrop(dataTransfer) {
        collectFromDataTransfer(dataTransfer).then(function (files) {
            if (!files.length) {
                return;
            }
            if (!window.FolderZip || !FolderZip.isFolderFileList(files)) {
                if (selectedCount) {
                    selectedCount.textContent = "Drop a folder here, or click to browse.";
                }
                return;
            }
            packFolderThenSelect(files);
        });
    }

    function bindDragTarget(el, onDrop) {
        if (!el || !onDrop) {
            return;
        }
        ["dragenter", "dragover"].forEach(function (evt) {
            el.addEventListener(evt, function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                el.classList.add("drag-active");
            });
        });
        el.addEventListener("dragleave", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            if (ev.currentTarget === el) {
                el.classList.remove("drag-active");
            }
        });
        el.addEventListener("dragend", function () {
            el.classList.remove("drag-active");
        });
        el.addEventListener("drop", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            el.classList.remove("drag-active");
            onDrop(ev.dataTransfer);
        });
    }

    if (dropzone && fileInput) {
        dropzone.addEventListener("click", function (ev) {
            ev.stopPropagation();
            fileInput.click();
        });
        dropzone.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                fileInput.click();
            }
        });
        bindDragTarget(dropzone, handleFileDrop);
    }

    if (folderPanel) {
        bindDragTarget(folderPanel, handleFolderDrop);
    }

    var encryptModal = document.getElementById("home-encrypt-modal");
    var pinModal = document.getElementById("home-pin-modal");
    var pinInput = document.getElementById("home-pin-input");
    var pinConfirm = document.getElementById("home-pin-confirm");
    var pinError = document.getElementById("home-pin-error");

    function doUpload() {
        if (packingFolder || !selectedFiles.length) {
            return;
        }
        transit();
        var fd = new FormData();
        selectedFiles.forEach(function (file) {
            fd.append("file", file, file.name);
        });
        var xhr = new XMLHttpRequest();
        var bar = document.getElementById("progress-bar");
        var pct = document.getElementById("progress-pct");
        var label = document.getElementById("progress-label");
        xhr.upload.addEventListener("progress", function (e) {
            if (e.lengthComputable && pct) {
                var percent = Math.round((e.loaded / e.total) * 100);
                if (bar) {
                    bar.style.width = percent + "%";
                }
                pct.textContent = percent + "%";
            } else if (pct) {
                pct.textContent = "...";
            }
        });
        xhr.addEventListener("load", function () {
            if (xhr.status >= 200 && xhr.status < 300) {
                if (label) {
                    label.textContent = "Done!";
                }
                if (bar) {
                    bar.style.width = "100%";
                }
                if (pct) {
                    pct.textContent = "100%";
                }
                setTimeout(function () { window.location.href = "/"; }, 600);
            } else {
                if (label) {
                    label.textContent = "Upload failed";
                }
                setTimeout(function () {
                    var b = document.getElementById("body");
                    if (b) {
                        b.style.visibility = "hidden";
                    }
                }, 2000);
            }
        });
        xhr.addEventListener("error", function () {
            if (label) {
                label.textContent = "Upload failed";
            }
            setTimeout(function () {
                var b = document.getElementById("body");
                if (b) {
                    b.style.visibility = "hidden";
                }
            }, 2000);
        });
        xhr.open("POST", form.action || "/");
        xhr.send(fd);
    }

    function showEncryptModal() {
        if (encryptModal) {
            encryptModal.classList.add("is-open");
            encryptModal.setAttribute("aria-hidden", "false");
        }
    }
    function hideEncryptModal() {
        if (encryptModal) {
            encryptModal.classList.remove("is-open");
            encryptModal.setAttribute("aria-hidden", "true");
        }
    }
    function showPinModal() {
        if (pinModal) {
            pinModal.classList.add("is-open");
            pinModal.setAttribute("aria-hidden", "false");
            if (pinInput) {
                pinInput.value = "";
            }
            if (pinConfirm) {
                pinConfirm.value = "";
            }
            if (pinError) {
                pinError.style.display = "none";
                pinError.textContent = "";
            }
            if (pinInput) {
                pinInput.focus();
            }
        }
    }
    function hidePinModal() {
        if (pinModal) {
            pinModal.classList.remove("is-open");
            pinModal.setAttribute("aria-hidden", "true");
        }
    }

    var encNo = document.getElementById("home-encrypt-no");
    var encYes = document.getElementById("home-encrypt-yes");
    var pinCancel = document.getElementById("home-pin-cancel");
    var pinSet = document.getElementById("home-pin-set");

    if (encNo) {
        encNo.addEventListener("click", function () { hideEncryptModal(); doUpload(); });
    }
    if (encYes) {
        encYes.addEventListener("click", function () { hideEncryptModal(); showPinModal(); });
    }
    if (pinCancel) {
        pinCancel.addEventListener("click", function () { hidePinModal(); doUpload(); });
    }
    if (pinSet) {
        pinSet.addEventListener("click", function () {
            var pin = pinInput ? pinInput.value : "";
            var conf = pinConfirm ? pinConfirm.value : "";
            if (pin.length < 4) {
                if (pinError) {
                    pinError.textContent = "PIN must be at least 4 characters";
                    pinError.style.display = "block";
                }
                return;
            }
            if (pin !== conf) {
                if (pinError) {
                    pinError.textContent = "PIN and Confirm PIN do not match";
                    pinError.style.display = "block";
                }
                return;
            }
            var folder = window.UPLOADER_FOLDER;
            if (!folder) {
                doUpload();
                return;
            }
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/uploads/" + encodeURIComponent(folder) + "/set-pin");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    hidePinModal();
                    doUpload();
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
            xhr.send(JSON.stringify({ pin: pin }));
        });
    }

    function getFolderThen(fn) {
        var folder = window.UPLOADER_FOLDER;
        if (folder) {
            fn(folder);
            return;
        }
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/uploader-folder");
        xhr.onload = function () {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    var r = JSON.parse(xhr.responseText);
                    folder = r && r.folder;
                } catch (z) {}
                if (folder) {
                    window.UPLOADER_FOLDER = folder;
                }
            }
            fn(window.UPLOADER_FOLDER || null);
        };
        xhr.onerror = function () { fn(null); };
        xhr.send();
    }

    function startUploadFlow() {
        if (packingFolder || !selectedFiles.length) {
            return;
        }
        var hasFolderXhr = new XMLHttpRequest();
        hasFolderXhr.open("GET", "/api/uploader-has-folder");
        hasFolderXhr.onload = function () {
            var hasFolder = true;
            try {
                var r = JSON.parse(hasFolderXhr.responseText);
                hasFolder = r && r.has_folder;
            } catch (z) {}
            if (hasFolder) {
                doUpload();
                return;
            }
            getFolderThen(function (folder) {
                if (!folder) {
                    doUpload();
                    return;
                }
                showEncryptModal();
            });
        };
        hasFolderXhr.onerror = function () { doUpload(); };
        hasFolderXhr.send();
    }

    if (uploadBtn) {
        uploadBtn.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            startUploadFlow();
        });
    }

    form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
    });
    renderSelectedFiles();
})();
