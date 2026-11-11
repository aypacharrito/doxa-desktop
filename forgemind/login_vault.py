"""Windows Credential Manager-backed logins. Passwords never enter model tool results."""
import json
from urllib.parse import urlsplit

SERVICE = 'Doxa.SiteLogins'


def origin(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Use the exact HTTPS login website, without credentials in its URL.')
    host = p.hostname.encode('idna').decode('ascii').lower()
    port = p.port
    return 'https://' + host + (f':{port}' if port and port != 443 else '')


class LoginVault:
    def __init__(self, store=None):
        if store is None:
            import keyring
            store = keyring
        self.store = store

    def _read(self):
        raw = self.store.get_password(SERVICE, 'labels')
        labels = json.loads(raw) if raw else []
        return {label: json.loads(value) for label in labels
                if (value := self.store.get_password(SERVICE, 'site:' + label))}

    def save(self, label, url, username, password, autofill=False):
        label = label.strip()
        if not label or len(label) > 80 or not username.strip() or not password:
            raise ValueError('Enter an account label, username and password.')
        rows = self._read()
        row = dict(origin=origin(url), username=username, password=password, autofill=bool(autofill))
        self.store.set_password(SERVICE, 'site:' + label, json.dumps(row))
        self.store.set_password(SERVICE, 'labels', json.dumps(sorted(set(rows) | {label})))

    def list(self):
        return [dict(label=k, origin=v['origin'], autofill=v.get('autofill', False))
                for k, v in self._read().items()]

    def remove(self, label):
        rows = self._read()
        if label in rows:
            self.store.delete_password(SERVICE, 'site:' + label)
        rows.pop(label, None)
        self.store.set_password(SERVICE, 'labels', json.dumps(sorted(rows)))

    def for_site(self, url, label=None):
        site = origin(url)
        matches = [v for k, v in self._read().items() if (label is None or label == k)
                   and v['origin'] == site and v.get('autofill')]
        if len(matches) != 1:
            raise ValueError('Choose one enabled login for this exact website in Login vault.')
        return matches[0]


def fill_login(page, vault=None):
    """Resolve locally, verify form destination, fill without exposing secrets to planners."""
    vault = vault or LoginVault()
    account = vault.for_site(page.url)
    passwords = page.locator('input[type="password"]:visible')
    if passwords.count() != 1:
        raise ValueError('Expected one visible login password field; complete this flow yourself.')
    password = passwords.first
    target = password.evaluate('(e) => e.form ? e.form.action : null')
    if not target or origin(target) != account['origin']:
        raise ValueError('The form destination differs from the saved website.')
    # Keep credentials out of screenshot fields other than the ordinary username input.
    form = password.locator('xpath=ancestor::form')
    users = form.locator('input[autocomplete="username"]:visible, input[type="email"]:visible, input[name="username"]:visible')
    if users.count() != 1:
        raise ValueError('Could not identify one username field; complete this flow yourself.')
    users.first.fill(account['username'])
    password.fill(account['password'])
    return 'Saved login filled locally for the exact website. No password was sent to an AI. Submit only when the owner task authorizes signing in.'
