(function () {
    var triggers = document.querySelectorAll(".js-file-preview-trigger");
    var activeToken = 0;
    var activeTrigger = null;
    var previewRow = null;
    var previewPanel = null;
    var previewTitle = null;
    var previewDownload = null;
    var previewContent = null;

    if (!triggers.length) {
        return;
    }

    function ensurePreviewElements() {
        if (previewRow) {
            return;
        }
        previewRow = document.createElement("li");
        previewRow.className = "file-preview-row";

        previewPanel = document.createElement("section");
        previewPanel.className = "file-preview-panel";
        previewPanel.setAttribute("aria-live", "polite");

        var header = document.createElement("div");
        header.className = "file-preview-header";

        previewTitle = document.createElement("h2");
        previewTitle.textContent = "Preview";

        previewDownload = document.createElement("a");
        previewDownload.className = "file-preview-download";
        previewDownload.textContent = "Download";
        previewDownload.href = "#";
        previewDownload.setAttribute("download", "");

        previewContent = document.createElement("div");
        previewContent.className = "file-preview-content";

        header.appendChild(previewTitle);
        header.appendChild(previewDownload);
        previewPanel.appendChild(header);
        previewPanel.appendChild(previewContent);
        previewRow.appendChild(previewPanel);
    }

    function setPreviewNode(node) {
        previewContent.innerHTML = "";
        previewContent.appendChild(node);
    }

    function setPreviewMessage(text) {
        var p = document.createElement("p");
        p.className = "file-preview-empty";
        p.textContent = text;
        setPreviewNode(p);
    }

    function looksTextual(contentType) {
        if (!contentType) {
            return false;
        }
        return (
            contentType.indexOf("text/") === 0 ||
            contentType.indexOf("json") > -1 ||
            contentType.indexOf("xml") > -1 ||
            contentType.indexOf("javascript") > -1
        );
    }

    function setRowActive(activeEl) {
        triggers.forEach(function (el) {
            if (el === activeEl) {
                el.classList.add("is-preview-active");
            } else {
                el.classList.remove("is-preview-active");
            }
        });
    }

    function closePreview() {
        activeToken += 1;
        if (previewContent) {
            previewContent.innerHTML = "";
        }
        if (previewRow && previewRow.parentNode) {
            previewRow.parentNode.removeChild(previewRow);
        }
        activeTrigger = null;
        setRowActive(null);
    }

    function renderPreview(triggerEl) {
        ensurePreviewElements();
        var fileName = triggerEl.getAttribute("data-file-name") || "File";
        var downloadUrl = triggerEl.getAttribute("data-download-url") || triggerEl.getAttribute("href");
        var previewUrl = triggerEl.getAttribute("data-preview-url") || (downloadUrl + "?preview=1");
        var clickedRow = triggerEl.closest("li");
        activeToken += 1;
        var token = activeToken;

        if (clickedRow && clickedRow.parentNode) {
            clickedRow.parentNode.insertBefore(previewRow, clickedRow.nextSibling);
        }

        previewTitle.textContent = fileName;
        previewDownload.href = downloadUrl;
        previewDownload.setAttribute("download", fileName);
        activeTrigger = triggerEl;
        setRowActive(triggerEl);
        setPreviewMessage("Loading preview...");

        fetch(previewUrl, { credentials: "same-origin" }).then(function (res) {
            if (token !== activeToken) {
                return;
            }
            if (!res.ok) {
                throw new Error("Preview failed");
            }
            var contentType = (res.headers.get("content-type") || "").toLowerCase();

            if (contentType.indexOf("image/") === 0) {
                var img = document.createElement("img");
                img.className = "file-preview-image";
                img.alt = fileName;
                img.src = previewUrl + (previewUrl.indexOf("?") === -1 ? "?" : "&") + "t=" + Date.now();
                setPreviewNode(img);
                return;
            }

            if (looksTextual(contentType)) {
                return res.text().then(function (text) {
                    if (token !== activeToken) {
                        return;
                    }
                    var pre = document.createElement("pre");
                    pre.className = "file-preview-text";
                    pre.textContent = text.slice(0, 200000);
                    setPreviewNode(pre);
                });
            }

            if (
                contentType.indexOf("pdf") > -1 ||
                contentType.indexOf("video/") === 0 ||
                contentType.indexOf("audio/") === 0
            ) {
                var frame = document.createElement("iframe");
                frame.className = "file-preview-embed";
                frame.src = previewUrl + (previewUrl.indexOf("?") === -1 ? "?" : "&") + "t=" + Date.now();
                frame.setAttribute("title", "File preview");
                setPreviewNode(frame);
                return;
            }

            setPreviewMessage("Preview is not available for this file type. Use Download.");
        }).catch(function () {
            if (token !== activeToken) {
                return;
            }
            setPreviewMessage("Could not load preview. You can still download the file.");
        });
    }

    triggers.forEach(function (triggerEl) {
        triggerEl.addEventListener("click", function (ev) {
            if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) {
                return;
            }
            ev.preventDefault();
            if (activeTrigger === triggerEl) {
                closePreview();
                return;
            }
            renderPreview(triggerEl);
        });
    });
})();
