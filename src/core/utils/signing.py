"""
From https://medium.com/@ekeydar/signed-urls-storage-for-django-58feecbd94a8
"""
from urllib import parse

from django.core.signing import Signer, BadSignature
from django.utils import timezone


def sign_url(url: str, hours: float, salt: str = "") -> str:
    """
    :param url: absolute url
    :param hours: hours till expiration
    :param salt: namespace of the signature: `check_signature` must be given the same
    :return: signed url, with two parameters signature and expires
    For example:
        sign_url("/protected/a.png", hours=1)
            '/protected/a.png?signature=W8utfRAt6uyrj1HE_CleRNYgVaE&expires=1552252400'
    """
    expires = int(timezone.now().timestamp() + hours * 3600)
    signer = Signer(salt=salt)
    full_value = '{}-{}'.format(url, expires)
    full_signature = signer.sign(full_value)
    signature = full_signature.split(signer.sep)[-1]  # just the signature part
    return '{}?{}'.format(url, parse.urlencode({
        'signature': signature,
        'expires': expires
    }))

def check_signature(url, salt: str = "") -> bool:
    """
    :param url: signed url (absolute path)
    :param salt: the salt the url was signed with
    :returns boolean
    get signed url, expected to be in the format
    /path/?signature=<signature>&expires=<expires>
    check signature and expires timestamp
    return True if ok
    """
    parsed_url = parse.urlparse(url)
    query_dict = parse.parse_qs(parsed_url.query)

    try:
        signature = query_dict['signature'][0]
        expires = int(query_dict['expires'][0])
    except (KeyError, ValueError):
        return False

    signer = Signer(salt=salt)
    full_value = '{}-{}'.format(parsed_url.path, expires)
    try:
        signer.unsign('{}{}{}'.format(full_value, signer.sep, signature))
    except BadSignature:
        return False
    return expires > timezone.now().timestamp()
