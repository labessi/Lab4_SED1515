from machine import UART, Pin
import sys
import select
import time

# -- configuration
UART_ID = 1            # H4 reliee a UART 1
BAUDRATE = 9600
BROCHE_TX = 8          # GP8 = TX
BROCHE_RX = 9          # GP9 = RX

PERIODE_KA_MS = 10_000         # keep-alive si aucun msg apres 10s
DELAI_SILENCE_MS = 35_000      # partenaire jugé déconnecté après 35s sans rien
TAILLE_MAX_RX = 256            # protection contre un tampon qui grossit sans fin
FIN = b'\n'

# 8 bits de données, pas de parité, 1 bit d'arrêt (8N1), identique des deux côtés
uart = UART(UART_ID, baudrate=BAUDRATE, bits=8, parity=None, stop=1,
            tx=Pin(BROCHE_TX), rx=Pin(BROCHE_RX))

# Lecture du clavier : poll() dit s'il y a un caractère à lire
clavier = select.poll()
clavier.register(sys.stdin, select.POLLIN)

# -- état
tampon_rx = b''                    # octets reçus pas encore terminés par '\n'
tampon_clavier = ''                # ligne en cours de saisie
dernier_envoi = time.ticks_ms()    # pour savoir quand envoyer un keep-alive
derniere_reception = time.ticks_ms()
partenaire_actif = False


# -- utilitaires
def heure_locale():
    """Heure locale du Pico au format hh:mm:ss."""
    t = time.localtime()
    return "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])


def afficher(texte):
    """Affiche une ligne sans perdre ce que l'utilisateur est en train de taper."""
    sys.stdout.write("\r\x1b[K" + texte + "\n")   # efface la ligne courante
    sys.stdout.write("> " + tampon_clavier)        # réaffiche la saisie en cours


def envoyer(type_msg, contenu):
    """Envoie une trame 'TYPE|contenu\\n' au Pico partenaire."""
    global dernier_envoi
    uart.write("{}|{}\n".format(type_msg, contenu).encode())
    dernier_envoi = time.ticks_ms()


# -- réception
def traiter_ligne(ligne):
    """Décode et affiche une ligne complète reçue du partenaire."""
    global partenaire_actif
    try:
        texte = ligne.decode().strip()
    except UnicodeError:
        afficher("[!] message corrompu ignoré")
        return

    i = texte.find('|')
    if i < 0:
        afficher("[!] message mal formé ignoré : " + texte)
        return
    type_msg, contenu = texte[:i], texte[i + 1:]

    if not partenaire_actif:
        afficher("[i] partenaire connecté")
        partenaire_actif = True

    if type_msg == "MSG":
        afficher("Partenaire : " + contenu)
    elif type_msg == "KA":
        afficher("[keep-alive du partenaire, heure " + contenu + "]")
    else:
        afficher("[!] type de message inconnu : " + type_msg)


def verifier_reception():
    """Lit les octets disponibles et traite chaque ligne complète."""
    global tampon_rx, derniere_reception
    if not uart.any():
        return
    donnees = uart.read()
    if donnees is None:          # read() peut renvoyer None 
        return
    derniere_reception = time.ticks_ms()
    tampon_rx += donnees

    # Un message peut arriver en plusieurs morceaux, ou plusieurs d'un coup
    i = tampon_rx.find(FIN)
    while i >= 0:
        traiter_ligne(tampon_rx[:i])
        tampon_rx = tampon_rx[i + 1:]
        i = tampon_rx.find(FIN)

    if len(tampon_rx) > TAILLE_MAX_RX:   # jamais de '\n' = donnees invalides
        tampon_rx = b''
        afficher("[!] tampon de réception vidé (données invalides)")


# -- clavier
def verifier_clavier():
    """Lit les caractères tapés un par un ; envoie la ligne sur Entrée."""
    global tampon_clavier
    while clavier.poll(0):
        c = sys.stdin.read(1)
        if c in ('\r', '\n'):                      # Entrée
            if tampon_clavier:
                envoyer("MSG", tampon_clavier)
                sys.stdout.write("\r\x1b[KMoi : " + tampon_clavier + "\n")
                tampon_clavier = ''
                sys.stdout.write("> ")
        elif c in ('\x08', '\x7f'):                # Retour arrière
            if tampon_clavier:
                tampon_clavier = tampon_clavier[:-1]
                sys.stdout.write("\b \b")
        elif c == '|' or c < ' ':                  # caractères réservés
            pass
        else:
            tampon_clavier += c
            sys.stdout.write(c)                    # écho du caractère tapé


# -- maintien
def verifier_keepalive():
    """Envoie un keep-alive si l'utilisateur n'a rien envoyé depuis un moment,
    et signale si le partenaire ne donne plus signe de vie."""
    global partenaire_actif
    maintenant = time.ticks_ms()
    if time.ticks_diff(maintenant, dernier_envoi) >= PERIODE_KA_MS:
        envoyer("KA", heure_locale())

    if partenaire_actif and time.ticks_diff(maintenant, derniere_reception) > DELAI_SILENCE_MS:
        afficher("[!] aucune nouvelle du partenaire, vérifiez le câblage")
        partenaire_actif = False


# -- programme principal
print("Chat UART prêt. Tapez un message puis Entrée (Ctrl+C pour quitter).")
sys.stdout.write("> ")

try:
    while True:
        verifier_reception()    # 1. messages entrants
        verifier_clavier()      # 2. saisie de l'utilisateur
        verifier_keepalive()    # 3. maintien de connexion
        time.sleep_ms(10)
except KeyboardInterrupt:
    print("\nFin du clavardage.")
