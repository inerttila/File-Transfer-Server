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
  var fileInput = document.getElementById("onetime-file");
  var dropzone = document.getElementById("onetime-dropzone");
  var doneBtn = document.getElementById("onetime-done-btn");
  var selectedEl = document.getElementById("onetime-selected");
  var resultEl = document.getElementById("onetime-result");
  var linkInput = document.getElementById("onetime-link-input");
  var copyBtn = document.getElementById("onetime-copy-btn");
  var copyStatus = document.getElementById("onetime-copy-status");
  var selectedFile = null;

  function updateSelectedLabel() {
    if (!selectedEl || !doneBtn) {
      return;
    }
    if (!selectedFile) {
      selectedEl.textContent = "";
      doneBtn.setAttribute("disabled", "disabled");
      return;
    }
    selectedEl.textContent = selectedFile.name;
    doneBtn.removeAttribute("disabled");
  }

  function setFile(file) {
    selectedFile = file || null;
    if (fileInput) {
      fileInput.value = "";
    }
    updateSelectedLabel();
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var f = fileInput.files && fileInput.files[0];
      setFile(f || null);
    });
  }

  if (dropzone && fileInput) {
    dropzone.addEventListener("click", function () {
      fileInput.click();
    });
    dropzone.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        fileInput.click();
      }
    });
    ["dragenter", "dragover"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        dropzone.classList.add("drag-active");
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        dropzone.classList.remove("drag-active");
      });
    });
    dropzone.addEventListener("drop", function (ev) {
      var files =
        ev.dataTransfer && ev.dataTransfer.files ? ev.dataTransfer.files : [];
      if (files.length) {
        setFile(files[0]);
      }
    });
  }

  if (doneBtn) {
    doneBtn.addEventListener("click", function () {
      if (!selectedFile) {
        return;
      }
      transit();
      var fd = new FormData();
      fd.append("file", selectedFile);
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
        var body = document.getElementById("body");
        if (body) {
          body.style.visibility = "hidden";
        }
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
          var data = null;
          try {
            data = JSON.parse(xhr.responseText);
          } catch (z) {}
          if (data && data.download_url && linkInput && resultEl) {
            linkInput.value = data.download_url;
            resultEl.hidden = false;
            try {
              sessionStorage.setItem("fts_onetime_share_completed", "1");
            } catch (e) {}
            var navOt = document.querySelector(".nav-onetime-link");
            if (navOt) {
              navOt.classList.add("nav-onetime-used");
            }
          }
        } else {
          if (label) {
            label.textContent = "Failed";
          }
          var err = "Could not create link.";
          try {
            var r = JSON.parse(xhr.responseText);
            if (r && r.error) {
              err = r.error;
            }
          } catch (z) {}
          alert(err);
        }
      });
      xhr.addEventListener("error", function () {
        var body = document.getElementById("body");
        if (body) {
          body.style.visibility = "hidden";
        }
        if (label) {
          label.textContent = "Failed";
        }
        alert("Network error.");
      });
      xhr.open("POST", "/api/one-time-link");
      xhr.send(fd);
    });
  }

  if (copyBtn && linkInput) {
    copyBtn.addEventListener("click", function () {
      var url = linkInput.value;
      if (!url) {
        return;
      }
      function ok() {
        if (copyStatus) {
          copyStatus.textContent = "Copied.";
        }
      }
      function fail() {
        if (copyStatus) {
          copyStatus.textContent =
            "Copy failed — select the link and copy manually.";
        }
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(ok).catch(fail);
      } else {
        linkInput.select();
        try {
          if (document.execCommand("copy")) {
            ok();
          } else {
            fail();
          }
        } catch (e) {
          fail();
        }
      }
    });
  }

  updateSelectedLabel();
})();
