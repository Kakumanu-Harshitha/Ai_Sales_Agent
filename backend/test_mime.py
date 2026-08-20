from email.message import EmailMessage

msg = EmailMessage()
msg.set_content("Plain text")
msg.add_alternative("<html><body><img src=\"cid:test_img\"></body></html>", subtype='html')

html_part = msg.get_payload()[1]
html_part.add_related(b"fake_image_data", maintype="image", subtype="png", cid="<test_img>")

print(msg.as_string())
