import os
from flask import Flask, flash, request, redirect, url_for
from werkzeug.utils import secure_filename
import sys
from datetime import date
import pathlib


def get_or_create_folder(folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    return folder_path


UPLOAD_FOLDER = get_or_create_folder("uploads")
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    return True


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    # print(">??>>>",request.remote_addr)
    tmp_path = str(date.today()) + "_" + \
        "-".join(str(request.remote_addr).split("."))

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        files = request.files.getlist("file")
        if not len(files):
            flash('No selected file')
            return redirect(request.url)
        if files:
            pathlib.Path(app.config['UPLOAD_FOLDER'],
                         tmp_path).mkdir(exist_ok=True)
            for file in files:
                filename = secure_filename(file.filename)
                file.save(os.path.join(
                    app.config['UPLOAD_FOLDER'], tmp_path, filename))
            return redirect(url_for('upload_file', name=filename))
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <style>
    input[type="file"] {
        display: none;
    }
    input[type="submit"] {
        display: none;
    }
    .custom-file-upload {
        border: 1px solid #ccc;
        display: inline-block;
        padding: 6px 12px;
        cursor: pointer;
    }

    .upload{
    background: red;
    }
.custom-file-upload {
    border: 10px solid #aaa;
    display: inline-block;
    padding: 6px 12px;
    cursor: pointer;
    width: 500px;
    height: 500px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    margin: 10px;
    font-size: 57px;
}

#body{
    visibility: hidden;
	min-height: 100vh;
	display: flex;
	justify-content: center;
	align-items: center;
    background: white;
    width: 100vw;
    height: 100vh;
    position: relative;
}
.main{
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;

}
ul{
position: absolute;
}
.spinner {
	--t: 2500ms;
	--animation: rotate var(--t) linear infinite;
	--animation2: scale var(--t) linear infinite alternate;
	position: relative;
	width: 10rem;
	height: 10rem;
	display: flex;
	justify-content: center;
	align-items: center;
	animation: var(--animation), var(--animation2);
}

.spinner::before,
.spinner::after {
	content: '';
	position: absolute;
}

.spinner::before {
	inset: 0;
	border: 3px solid turquoise;
	border-radius: 50%;
	mask-image: conic-gradient(transparent 10%, black);
	animation: borderScale var(--t) linear infinite alternate;
}

.spinner::after {
	--r: 45deg;
	--scale: 2;
	width: 20%;
	height: 20%;
	background: 
		radial-gradient(circle at 30% 35%, white 3px, transparent 0),
		radial-gradient(circle at 70% 35%, white 3px, transparent 0),
		radial-gradient(circle at top center, white 6px, transparent 0),
		turquoise;
	background-position: 0 0, 0 0, 0 1.25rem;
	top: 0;
	translate: 0 -50%;
	rotate: 45deg;
	animation: var(--animation) reverse, var(--animation2);
	border-radius: 20%;
}

@keyframes rotate {
	to {
		rotate: calc(360deg + var(--r, 0deg));
	}
}

@keyframes scale {
	to {
		scale: var(--scale, 0.5);
	}
}

@keyframes borderScale {
	to {
		border: 6px solid turquoise;
	}
}
    @media screen and (min-width: 1000px){
    .custom-file-upload {
    border: 10px solid #aaa;
    display: inline-block;
    padding: 6px 12px;
    cursor: pointer;
    width: 250px;
    height: 250px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    margin: 10px;
    font-size: 30px;
}
    }
    @media screen and (max-width: 1000px){
    .spinner::after {
        --r: 45deg;
        --scale: 2;
        width: 20%;
        height: 20%;
        background: radial-gradient(circle at 30% 50%, white 8px, transparent 0), radial-gradient(circle at 70% 50%, white 8px, transparent 0), radial-gradient(circle at 50% -3%, white 28px, transparent 0), turquoise;
        background-position: 0 0, 0 0, 0 1.25rem;
        top: 0;
        translate: 0 -50%;
        rotate: 45deg;
        animation: var(--animation) reverse, var(--animation2);
        border-radius: 20%;
    }
    .spinner {
    --t: 2500ms;
    --animation: rotate var(--t) linear infinite;
    --animation2: scale var(--t) linear infinite alternate;
    position: relative;
    width: 40rem;
    height: 40rem;
    display: flex;
    justify-content: center;
    align-items: center;
    animation: var(--animation), var(--animation2);
}
.spinner::before {
    inset: 0;
    border: 3px solid turquoise;
    border-radius: 50%;
    mask-image: conic-gradient(transparent 10%, black);
    animation: borderScale var(--t) linear infinite alternate;
}
    }
    </style>
    <div class="main">
    <form method=post enctype=multipart/form-data>
        <input id="k-upload" onchange="enablethis(this)" class="files" type="file" name="file" multiple>
        <label for="k-upload" class="custom-file-upload">
            <i class="fa fa-cloud-upload"></i>Select Files
        </label>


        <input onclick="transit()" id="file-upload" class="submiter" disabled type=submit value="Upload">
        <label for="file-upload" class="custom-file-upload upload">
            <i class="fa fa-cloud-upload"></i>Upload
        </label>
    </form>
    <div>
    <ul id="is">
    </ul>
    </div>

    </div>
    <div id="body">
<div class="spinner"></div>
    </div>
    <script>
    function transit(){
        document.getElementById("body").style.visibility = "visible"
    }
        function enablethis(e){
            document.getElementsByClassName("upload")[0].style.background = "#00ff8069"
            document.getElementsByClassName("submiter")[0].removeAttribute("disabled")
            let ul = document.getElementById("is")
            const li = text => {
                var l = document.createElement('li');
                l.innerText = text;
                return l
            }
            [...e.files].forEach( el => {
                ul.appendChild(li(el.name))
            }
            )
        }

    </script>
    '''


if __name__ == "__main__":
    if sys.argv[-1]:
        if sys.argv[-1] == "80":  # NAME
            # python server.py {the name above}
            app.run(host="1921111", port="80")
        if sys.argv[-1] == "help":
            print("\nExamples:\n\tDev: python server.py\n\tDeploy: python server.py deploy\n\tDeploy custom port: python server.py <9598>\n\n")
        else:
            try:
                app.run(host="192111111", port=sys.argv[-1])
            except:
                print("Cannot open port", sys.argv[-1])
                print("Running on localhost:5000")
                app.debug = True
                app.run()
