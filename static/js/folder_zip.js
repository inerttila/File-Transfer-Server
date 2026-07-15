/**
 * Pack a folder selection (files with webkitRelativePath) into one .zip File.
 * Requires global fflate (static/js/vendor/fflate.min.js).
 */
(function (global) {
    function relativePath(file) {
        return file.webkitRelativePath || file.name || "file";
    }

    function isFolderFileList(files) {
        if (!files || !files.length) {
            return false;
        }
        for (var i = 0; i < files.length; i++) {
            var p = relativePath(files[i]);
            if (p.indexOf("/") === -1) {
                return false;
            }
        }
        return true;
    }

    function folderDisplayName(files) {
        var first = relativePath(files[0]);
        var slash = first.indexOf("/");
        if (slash > 0) {
            return first.slice(0, slash);
        }
        return "folder";
    }

    function readFileAsUint8(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () {
                resolve(new Uint8Array(reader.result));
            };
            reader.onerror = function () {
                reject(reader.error || new Error("Could not read file"));
            };
            reader.readAsArrayBuffer(file);
        });
    }

    /**
     * @param {File[]} files
     * @param {(done: number, total: number) => void} [onProgress]
     * @returns {Promise<File>}
     */
    function zipFolderFiles(files, onProgress) {
        if (!global.fflate || !global.fflate.zip) {
            return Promise.reject(new Error("Zip library not loaded"));
        }
        var total = files.length;
        var name = folderDisplayName(files);
        var zipName = name + ".zip";
        var map = {};
        var index = 0;

        function readNext() {
            if (index >= total) {
                return Promise.resolve(map);
            }
            var file = files[index];
            var path = relativePath(file);
            var i = index;
            index += 1;
            if (onProgress) {
                onProgress(i, total);
            }
            return readFileAsUint8(file).then(function (data) {
                map[path] = data;
                return readNext();
            });
        }

        return readNext().then(function (fileMap) {
            return new Promise(function (resolve, reject) {
                global.fflate.zip(fileMap, { level: 6 }, function (err, data) {
                    if (err) {
                        reject(err);
                        return;
                    }
                    var blob = new Blob([data], { type: "application/zip" });
                    resolve(new File([blob], zipName, { type: "application/zip", lastModified: Date.now() }));
                });
            });
        });
    }

    global.FolderZip = {
        isFolderFileList: isFolderFileList,
        folderDisplayName: folderDisplayName,
        zipFolderFiles: zipFolderFiles,
    };
})(typeof window !== "undefined" ? window : this);
