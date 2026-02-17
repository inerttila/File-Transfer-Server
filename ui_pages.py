import datetime
from urllib.parse import quote

from flask import render_template, url_for


GIPHY_LOGO_URL = (
    "https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif"
    "?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&rid=giphy.gif"
)

NAV_LOGO = (
    '<a href="/" class="nav-logo-link"><img src="'
    + GIPHY_LOGO_URL
    + '" alt="Logo" class="nav-logo"></a>'
)
HOME_ICON = (
    '<svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" '
    'viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 '
    '01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 '
    '1m-6 0h6"/></svg>'
)
UPLOADS_ICON = (
    '<svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" fill="none" '
    'viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 '
    '00-2 2z"/></svg>'
)

NAV_HTML = (
    '<nav class="site-nav">'
    + NAV_LOGO
    + '<a href="/">'
    + HOME_ICON
    + 'Home</a><a href="/uploads">'
    + UPLOADS_ICON
    + "Uploads</a></nav>"
)
NAV_HTML_HOME_ACTIVE = (
    '<nav class="site-nav">'
    + NAV_LOGO
    + '<a href="/" class="active">'
    + HOME_ICON
    + 'Home</a><a href="/uploads">'
    + UPLOADS_ICON
    + "Uploads</a></nav>"
)
NAV_HTML_UPLOADS_ACTIVE = (
    '<nav class="site-nav">'
    + NAV_LOGO
    + '<a href="/">'
    + HOME_ICON
    + 'Home</a><a href="/uploads" class="active">'
    + UPLOADS_ICON
    + "Uploads</a></nav>"
)


def _esc(text):
    text = "" if text is None else str(text)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_size(num_bytes):
    size = int(num_bytes or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _toggle_sort_link(current_sort, key):
    if current_sort == key:
        return f"-{key}"
    if current_sort == f"-{key}":
        return key
    return key if key == "name" else f"-{key}"


def render_uploads_page(title, breadcrumb_html, items, list_class="card-list", nav_html=None, current_sort="-mtime"):
    if nav_html is None:
        nav_html = NAV_HTML_UPLOADS_ACTIVE
    if items:
        bin_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" '
            'stroke="currentColor" stroke-width="2"><path stroke-linecap="round" '
            'stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 '
            '0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 '
            '1v3M4 7h16"/></svg>'
        )
        download_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" '
            'stroke="currentColor" stroke-width="2"><path stroke-linecap="round" '
            'stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4m5 8H3"/></svg>'
        )
        list_items = []
        is_file_table = list_class == "files-table"
        is_file_list = "files" in list_class.split() or is_file_table
        for item in items:
            li_class = ' class="file-row"' if (is_file_list or item.get("delete_url") or item.get("pin_menu")) else ""
            label_html = (
                '<span class="lock-icon" title="Protected" aria-hidden="true">&#128274;</span> '
                if item.get("has_pin")
                else ""
            ) + _esc(item["label"])
            link_attrs = f'href="{item["url"]}"'
            if is_file_list:
                safe_label = _esc(item["label"])
                link_attrs += (
                    ' class="js-file-preview-trigger"'
                    f' data-file-name="{safe_label}"'
                    f' data-download-url="{item["url"]}"'
                    f' data-preview-url="{item["url"]}?preview=1"'
                )
            link = f"<a {link_attrs}>{label_html}</a>"
            if is_file_table:
                mtime = int(item.get("mtime") or 0)
                mtime_text = (
                    datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    if mtime
                    else "-"
                )
                actions = (
                    f'<a href="{item["url"]}" class="download-btn" aria-label="Download">{download_svg}</a>'
                )
                if item.get("delete_url"):
                    msg = item.get("delete_message", "Delete?")
                    actions += (
                        f'<form method="post" action="{item["delete_url"]}" class="delete-form js-delete-form" '
                        f'data-confirm-message="{msg}"><button type="button" class="delete-btn '
                        f'js-delete-trigger" aria-label="Delete">{bin_svg}</button></form>'
                    )
                row_html = (
                    '<tr class="file-table-row" data-preview-row="1">'
                    f'<td class="file-name-cell">{link}</td>'
                    f'<td class="file-size-cell">{_format_size(item.get("size", 0))}</td>'
                    f'<td class="file-mtime-cell">{mtime_text}</td>'
                    f'<td class="file-actions-cell"><span class="row-actions-table">{actions}</span></td>'
                    "</tr>"
                )
                list_items.append(row_html)
                continue
            if is_file_list:
                link += '<span class="row-actions">'
                link += (
                    f'<a href="{item["url"]}" class="download-btn" aria-label="Download">{download_svg}</a>'
                )
                if item.get("delete_url"):
                    msg = item.get("delete_message", "Delete?")
                    link += (
                        f'<form method="post" action="{item["delete_url"]}" class="delete-form js-delete-form" '
                        f'data-confirm-message="{msg}"><button type="button" class="delete-btn '
                        f'js-delete-trigger" aria-label="Delete">{bin_svg}</button></form>'
                    )
                link += "</span>"
            elif item.get("pin_menu"):
                folder_esc = (item.get("folder_name") or "").replace("&", "&amp;").replace('"', "&quot;")
                has_pin = "true" if item.get("has_pin") else "false"
                link += (
                    '<span class="row-actions"><button type="button" class="pin-menu-btn js-pin-menu" '
                    f'data-folder="{folder_esc}" data-has-pin="{has_pin}" '
                    'aria-label="Folder options">&#8230;</button>'
                )
            if item.get("delete_url") and not is_file_list:
                msg = item.get("delete_message", "Delete?")
                link += (
                    f'<form method="post" action="{item["delete_url"]}" class="delete-form js-delete-form" '
                    f'data-confirm-message="{msg}"><button type="button" class="delete-btn '
                    f'js-delete-trigger" aria-label="Delete">{bin_svg}</button></form>'
                )
            if item.get("pin_menu"):
                link += "</span>"
            list_items.append(f"<li{li_class}>{link}</li>")
        if is_file_table:
            name_sort = _toggle_sort_link(current_sort, "name")
            size_sort = _toggle_sort_link(current_sort, "size")
            mtime_sort = _toggle_sort_link(current_sort, "mtime")
            body_html = (
                '<div class="table-container">'
                '<table class="uploads-table">'
                "<thead><tr>"
                f'<th><a href="?sort={name_sort}">Name</a></th>'
                f'<th><a href="?sort={size_sort}">Size</a></th>'
                f'<th><a href="?sort={mtime_sort}">Last Modified</a></th>'
                "<th>Actions</th>"
                "</tr></thead>"
                f'<tbody>{"".join(list_items)}</tbody>'
                "</table>"
                "</div>"
            )
        else:
            body_html = f'<ul class="{list_class}">{"".join(list_items)}</ul>'
    else:
        body_html = '<p class="empty">No items here yet.</p>'

    return render_template(
        "uploads.html",
        favicon_url=GIPHY_LOGO_URL,
        title=title,
        nav_html=nav_html,
        breadcrumb_html=breadcrumb_html,
        body_html=body_html,
    )


def render_folder_not_found_page():
    return render_template("folder_not_found.html", favicon_url=GIPHY_LOGO_URL)


def render_pin_entry_page(
    folder_name,
    next_url,
    error=None,
    form_action=None,
    show_final_attempt_popup=False,
):
    if form_action is None:
        form_action = url_for("pin_entry", folder=folder_name)
    return render_template(
        "pin_entry.html",
        favicon_url=GIPHY_LOGO_URL,
        folder_name=quote(folder_name),
        next_value=quote(next_url or ("/uploads/" + quote(folder_name))),
        error=error,
        form_action=form_action,
        show_final_attempt_popup=show_final_attempt_popup,
    )


def render_home_page(uploader_ip):
    return render_template(
        "home.html",
        favicon_url=GIPHY_LOGO_URL,
        nav_html=NAV_HTML_HOME_ACTIVE,
        uploader_folder=uploader_ip,
    )
