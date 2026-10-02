export const meta = {
  name: 'circuit-technique',
  description: "Circuit 3 de CLAUDE.md (correction technique) : coder implemente une issue, un agent execute les batteries, audit leger sur le diff, au plus une reprise, arret a tout point de decision. N'ecrit rien dans l'historique : ni commit, ni push, ni regeneration de reference, ni issue.",
  whenToUse: "Uniquement sur commande explicite du mainteneur, avec en argument le numero d'une issue de correction technique de la branche de travail courante (par ex. '76', ou '76 consigne complementaire'). Jamais de la propre initiative d'une session, d'un agent ou d'un hook. Pas pour une evolution de fond ni pour la revue finale complete avant fusion (regle 10).",
  phases: [
    { title: 'Préparation', detail: "Etat du depot au lancement : branche, tete, amont, arbre de travail propre" },
    { title: 'Implémentation', detail: "coder implemente l'issue, sans commit, push, regeneration ni issue" },
    { title: 'Vérification', detail: "Execution des batteries et controle des garde-fous" },
    { title: 'Audit léger', detail: "audit lit le diff contre la tete au lancement et les fonctions touchees" },
    { title: 'Reprise', detail: "Au plus une reprise de coder sur les constats bloquants ou majeurs corrigeables" },
    { title: 'Vérification de la reprise', detail: "Batteries et garde-fous apres la reprise" },
    { title: 'Audit de la reprise', detail: "audit lit le diff de la seule correction" }
  ]
}

// ---------------------------------------------------------------------------
//  Workflow circuit-technique : circuit 3 de CLAUDE.md (coder -> audit),
//  selon les huit principes de CLAUDE.md, « Sous-agents », « Workflows ».
//
//  Garde-fous et leurs limites :
//  - Principe 2 : un script de workflow ne peut pas retirer d'outils a un
//    agent, et .claude/settings.json autorise git commit et git push sans
//    dialogue. L'interdiction n'est donc PAS imposee par construction : elle
//    est portee par la consigne de chaque agent() et par les fiches, puis
//    CONTROLEE apres chaque tour (tete, amont et ZONES_PROTEGEES inchanges) ;
//    une violation detectee arrete le workflow. La session principale
//    verifie en outre git status et git log apres chaque workflow.
//  - Principe 3 : arret des qu'un constat releve d'expert ou du mainteneur,
//    ou que deux verifications se contredisent. Questions pour expert : pas
//    de reprise ; statut 'termine avec questions' seulement si les seules
//    remontees sont des questions, sinon 'arrete'.
//  - Principe 4 : au plus une reprise (deux tours coder -> audit).
//  - Principe 7 : les batteries sont des scripts executes par un agent ; le
//    script du workflow n'a pas acces au systeme de fichiers.
//  - Principe 8 : effort 'low' pour les etapes mecaniques ; model non fixe.
//  Le workflow ne propose qu'un message de commit ; il ne l'execute pas.
//  La copie des fichiers non suivis (mktemp -d, hors depot, tour 1) n'est pas
//  supprimee par le workflow : son chemin est rendu dans copie_temporaire.
// ---------------------------------------------------------------------------

// A ADAPTER : batteries de verification, identiques a CLAUDE.md, « Commandes »
// (commande complete, lancee depuis la racine du depot)
const BATTERIES = [
  // 'Rscript tests/test_unitaires.R',
  // 'pytest -q',
]

// A ADAPTER : repertoires que ni coder ni audit ne doivent toucher dans un
// workflow (references de non-regression, documentation de fond : regle 9)
const ZONES_PROTEGEES = [
  // 'tests/reference/',
  // 'docs/doc/',
]

// Consigne commune a tous les agents du workflow (principe 2)
const INTERDITS = [
  "INTERDICTIONS ABSOLUES dans ce workflow (CLAUDE.md, principe 2 des workflows) :",
  "- aucune commande git qui ecrit, notamment (liste non limitative) : git commit, git push, git add, git rm, git mv, git stash (sauf git stash create a l'etape Verification du tour 1), git reset, git checkout, git restore, git switch, git clean, git apply, git cherry-pick, git merge, git rebase, git tag, git update-ref, git branch <nom> / -d / -D ;",
  "- aucune regeneration ni modification des references de non-regression ;",
  "- aucune creation ni modification d'issue ou de commentaire GitHub ;",
  "- aucune modification de : " + (ZONES_PROTEGEES.length ? ZONES_PROTEGEES.join(', ') : '(aucune zone declaree)') + ".",
  "Si ta tache semble exiger l'un de ces actes, ne le fais pas : dis-le dans ta reponse, la session principale decidera."
].join('\n')

// Validation positive des sorties de l'etape Verification : tout ce qui n'est
// pas un hash d'objet git ou un chemin absolu est traite comme absent
const instantaneValide = function (v) { return /^[0-9a-f]{7,40}$/.test(String(v || '').trim()) }
const copieValide = function (v) { return /^(\/|[A-Za-z]:[\\/])/.test(String(v || '').trim()) }

// Fichiers non suivis, un chemin par ligne, sans guillemets ni echappement
const LISTE_NON_SUIVIS = 'git status --porcelain -z --untracked-files=all | tr "\\0" "\\n" | sed -n "s/^?? //p"'

// Argument : numero d'issue, suivi d'une consigne facultative.
// Formes acceptees : 76, '76', '#76 consigne', {issue: 76, consigne: '...'}
function lireArgs(a) {
  let v = (typeof a === 'undefined') ? null : a
  if (typeof v === 'string') {
    try { v = JSON.parse(v) } catch (e) { /* chaine libre : lue plus bas */ }
  }
  if (v !== null && typeof v === 'object') {
    const n = String(v.issue === undefined || v.issue === null ? '' : v.issue).match(/\d+/)
    return { issue: n ? n[0] : null, consigne: v.consigne ? String(v.consigne) : '' }
  }
  const brut = v === null ? '' : String(v)
  const m = brut.match(/^\s*#?(\d+)\b/)
  return { issue: m ? m[1] : null, consigne: m ? brut.slice(m[0].length).trim() : '' }
}
const entree = lireArgs(typeof args === 'undefined' ? undefined : args)
const issue = entree.issue
const consigne = entree.consigne

// Rapport final, complete au fil des phases ; questions pour expert en tete
const rapport = {
  questions_expert: [],
  issue: issue,
  statut: 'en cours',
  motif_arret: null,
  depot: null,
  tours: [],
  fichiers_modifies: [],
  surface_documentaire: [],
  commit_propose_non_execute: null,
  copie_temporaire: 'aucun',
  rappel: "Aucun commit, push, regeneration de reference ni issue n'a ete execute par le workflow. La session principale verifie git status et git log, puis commite apres lecture. Le repertoire copie_temporaire (hors depot) est a supprimer par la session principale apres lecture."
}

function arreter(motif) {
  rapport.statut = 'arrete'
  rapport.motif_arret = motif
  log('Arret : ' + motif)
  return rapport
}

function arreterReprise(motif) {
  const n = rapport.questions_expert.length
  return arreter(n > 0 ? motif + ' ; ' + n + ' question(s) pour expert en tete du rapport' : motif)
}

function terminerAvecQuestions() {
  rapport.statut = 'termine avec questions'
  rapport.motif_arret = rapport.questions_expert.length + ' question(s) pour expert, sans reprise'
  log('Fin avec questions pour expert : ' + rapport.motif_arret)
  return rapport
}

// ---------------------------------------------------------------------------
//  Schemas des sorties structurees
// ---------------------------------------------------------------------------

const SCHEMA_DEPOT = {
  type: 'object',
  properties: {
    branche: { type: 'string' },
    tete: { type: 'string', description: 'git rev-parse HEAD' },
    amont: { type: 'string', description: "git rev-parse @{u}, ou 'aucun'" },
    arbre_propre: { type: 'boolean', description: 'git status --porcelain vide' },
    status_porcelain: { type: 'string' }
  },
  required: ['branche', 'tete', 'amont', 'arbre_propre', 'status_porcelain']
}

const SCHEMA_IMPLEMENTATION = {
  type: 'object',
  properties: {
    fichiers_modifies: {
      type: 'array',
      items: {
        type: 'object',
        properties: { fichier: { type: 'string' }, changement: { type: 'string' } },
        required: ['fichier', 'changement']
      }
    },
    mesures: {
      type: 'array',
      description: 'Mesure derriere chaque affirmation sur le comportement du code',
      items: {
        type: 'object',
        properties: { affirmation: { type: 'string' }, commande: { type: 'string' }, sortie: { type: 'string' } },
        required: ['affirmation', 'commande', 'sortie']
      }
    },
    resultats_modifies: { type: 'string', description: "Tableau avant / apres, ou 'aucun'" },
    surface_documentaire: {
      type: 'array',
      description: 'Endroits de la documentation que docwriter devra rouvrir',
      items: { type: 'string' }
    },
    commit_propose: { type: 'string', description: 'Message de commit propose, NON execute' },
    doutes_expert: { type: 'array', items: { type: 'string' } },
    decision_requise: {
      type: 'boolean',
      description: "Vrai si la suite exige expert ou le mainteneur (choix de fond, resultat modifie a viser, acte interdit)"
    },
    motif_decision: { type: 'string' }
  },
  required: ['fichiers_modifies', 'mesures', 'resultats_modifies', 'surface_documentaire', 'commit_propose', 'doutes_expert', 'decision_requise', 'motif_decision']
}

const SCHEMA_VERIFICATION = {
  type: 'object',
  properties: {
    batteries: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          commande: { type: 'string' },
          code_sortie: { type: 'integer' },
          synthese: { type: 'string', description: 'Lignes de bilan de la sortie, recopiees telles quelles' }
        },
        required: ['commande', 'code_sortie', 'synthese']
      }
    },
    ecart_aux_references: {
      type: 'boolean',
      description: 'Vrai si une batterie echoue par ecart a une reference de non-regression (visa a demander)'
    },
    garde_fous: {
      type: 'object',
      properties: {
        tete_inchangee: { type: 'boolean' },
        amont_inchange: { type: 'boolean' },
        zones_intactes: { type: 'boolean', description: 'git status --porcelain vide sur chaque zone protegee' },
        detail: { type: 'string' }
      },
      required: ['tete_inchangee', 'amont_inchange', 'zones_intactes', 'detail']
    },
    instantane: { type: 'string', description: "Hash rendu par git stash create, ou 'aucun'" },
    copie_non_suivis: { type: 'string', description: "Chemin ABSOLU de la copie hors depot des fichiers non suivis, ou 'aucun'" }
  },
  required: ['batteries', 'ecart_aux_references', 'garde_fous', 'instantane', 'copie_non_suivis']
}

const SCHEMA_AUDIT = {
  type: 'object',
  properties: {
    conclusion: { type: 'string', enum: ['conforme', 'conforme avec reserves', 'non conforme'] },
    constats: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          gravite: { type: 'string', enum: ['bloquant', 'majeur', 'mineur'] },
          fichier_ligne: { type: 'string', description: 'fichier:ligne' },
          description: { type: 'string', description: 'Scenario concret : entrees -> sortie fausse' },
          mesure: {
            type: 'object',
            properties: { commande: { type: 'string' }, sortie: { type: 'string' } },
            required: ['commande', 'sortie']
          },
          correction_suggeree: { type: 'string' },
          releve_de: {
            type: 'string',
            enum: ['coder', 'expert', 'mainteneur'],
            description: "coder si corrigeable sans decision ; sinon qui doit trancher"
          }
        },
        required: ['gravite', 'fichier_ligne', 'description', 'mesure', 'correction_suggeree', 'releve_de']
      }
    },
    verifications_executees: {
      type: 'array',
      items: {
        type: 'object',
        properties: { commande: { type: 'string' }, resultat: { type: 'string' } },
        required: ['commande', 'resultat']
      }
    },
    questions_expert: { type: 'array', items: { type: 'string' } },
    contradiction_avec_batteries: {
      type: 'boolean',
      description: 'Vrai si ta conclusion contredit le resultat des batteries fourni'
    }
  },
  required: ['conclusion', 'constats', 'verifications_executees', 'questions_expert', 'contradiction_avec_batteries']
}

// ---------------------------------------------------------------------------
//  Consignes des etapes
// ---------------------------------------------------------------------------

function consigneImplementation(base, constats) {
  const lignes = [
    "Tu es lance par le workflow circuit-technique (circuit 3 de CLAUDE.md) pour l'issue #" + issue + " du depot courant.",
    "Lis l'issue et ses commentaires (mcp__github__issue_read, methodes get et get_comments, ou gh issue view " + issue + " --comments), puis ta fiche et CLAUDE.md, et applique leurs regles de travail.",
    "Tete de branche au lancement du workflow : " + base + ". Ne change pas de branche."
  ]
  if (consigne) lignes.push("Consigne complementaire du mainteneur : " + consigne)
  if (constats) {
    lignes.push(
      "REPRISE (unique) : corrige exactement les constats suivants de l'audit leger (et, s'il y en a, les batteries en echec listees), et rien d'autre. Chaque correction s'adosse a une mesure que tu cites.",
      JSON.stringify(constats, null, 2)
    )
  }
  lignes.push(
    INTERDITS,
    "Batteries : " + BATTERIES.join(' ; ') + ". En cas d'ecart aux references, produis le tableau avant / apres et explique chaque ligne, mais NE regenere PAS : mets decision_requise a vrai (visa et regeneration appartiennent a la session principale et au mainteneur).",
    "Mets aussi decision_requise a vrai si un resultat final ou un verdict change, si la tache exige un choix de fond, ou si elle semble exiger un acte interdit ; motif_decision le dit.",
    "surface_documentaire : endroits de la documentation que docwriter devra rouvrir ; liste vide si aucun.",
    "commit_propose : message au format de CLAUDE.md (prefixe de domaine, renvoi a #" + issue + ", surface d'impact documentaire, tableau avant / apres s'il y a lieu). Il ne sera PAS execute par le workflow."
  )
  return lignes.join('\n\n')
}

function consigneVerification(depot, figer) {
  const zones = ZONES_PROTEGEES.map(function (z) { return 'git status --porcelain -- ' + z }).join(' ; ')
  const lignes = [
    "Etape mecanique du workflow circuit-technique (principe 7) : tu executes des scripts et tu rapportes leur sortie ; tu ne juges pas le code et tu ne modifies aucun fichier du depot.",
    INTERDITS,
    "1. Depuis la racine du depot, execute dans cet ordre et rapporte pour chacune la commande, le code de sortie et les lignes de bilan recopiees telles quelles :",
    BATTERIES.map(function (b) { return '   ' + b }).join('\n'),
    "   ecart_aux_references est vrai si une batterie echoue par ecart a une reference de non-regression.",
    "2. Garde-fous : compare git rev-parse HEAD a " + depot.tete + " et git rev-parse @{u} a '" + depot.amont + "' ('aucun' si pas d'amont) ; " +
      (zones ? "les sorties de " + zones + " doivent etre vides (zones_intactes)" : "aucune zone protegee : zones_intactes vaut vrai") +
      ". Recopie les sorties dans detail."
  ]
  if (figer) {
    lignes.push("3. Instantane pour l'audit d'une eventuelle reprise : execute git stash create (objet sans reference ; seule commande git d'ecriture permise) et rends le hash, ou 'aucun' si la sortie est vide ; copie les fichiers non suivis, listes par " + LISTE_NON_SUIVIS + ", dans un repertoire cree par mktemp -d, HORS du depot, en conservant leurs chemins relatifs : COPIE=$(mktemp -d); " + LISTE_NON_SUIVIS + " | while IFS= read -r f; do cp --parents -- \"$f\" \"$COPIE\"; done ; rends le chemin absolu de COPIE, ou 'aucun' s'il n'y a aucun fichier non suivi.")
  } else {
    lignes.push("3. Pas d'instantane a ce tour : rends 'aucun' pour instantane et copie_non_suivis.")
  }
  return lignes.join('\n')
}

function consigneAudit(depot, verif, reference, tour, aVerifier) {
  const copie = (reference && copieValide(reference.copie_non_suivis)) ? reference.copie_non_suivis.trim() : null
  const perimetre = tour === 1
    ? "le travail en cours contre la tete au lancement : git diff " + depot.tete + ", plus les fichiers non suivis listes par " + LISTE_NON_SUIVIS + " (lis-les en entier)."
    : "la SEULE correction de la reprise : (a) fichiers suivis : git diff " +
      (instantaneValide(reference.instantane) ? reference.instantane.trim() : depot.tete + " (aucun fichier suivi modifie au tour 1)") +
      " ; (b) fichiers non suivis deja presents au tour 1 : " +
      (copie ? "pour chaque fichier de la copie (cd \"" + copie + "\" && find . -type f), diff entre la copie et le fichier du depot" : "aucun") +
      " ; (c) fichiers non suivis crees a la reprise, a lire en entier : " +
      (copie
        ? "les lignes de comm -13 <(cd \"" + copie + "\" && find . -type f | sed 's|^\\./||' | sort) <(" + LISTE_NON_SUIVIS + " | sort)"
        : "tous les fichiers de " + LISTE_NON_SUIVIS + " (aucun fichier non suivi au tour 1)") +
      "."
  const lignes = [
    "Audit LEGER du workflow circuit-technique, issue #" + issue + ", tour " + tour + ". Applique ta fiche, section audit leger.",
    "Perimetre : " + perimetre + " Lis les fonctions touchees avec leurs appelants et appeles, pas les fichiers entiers. Ce n'est pas la revue finale complete (regle 10).",
    INTERDITS,
    "Resultats des batteries executees juste avant (ne les relance pas sauf besoin d'une mesure precise) :",
    JSON.stringify(verif.batteries, null, 2),
    "Chaque constat porte sa gravite, fichier:ligne, la mesure executee (commande et sortie) et releve_de : 'coder' s'il se corrige sans decision, sinon 'expert' (question de fond) ou 'mainteneur' (resultat final, verdict, reference a regenerer). Un constat sans mesure ni emplacement n'est pas recevable.",
    "contradiction_avec_batteries : vrai si tu conclus conforme alors qu'une batterie echoue, ou l'inverse sans explication."
  ]
  if (tour === 2) {
    lignes.push(
      "La reprise devait corriger les constats et batteries en echec suivants du tour 1. Verifie que CHACUN est resolu, par une mesure ; tout element non resolu devient un constat de gravite egale (une batterie en echec non resolue : constat bloquant).",
      JSON.stringify(aVerifier, null, 2)
    )
  }
  return lignes.join('\n\n')
}

// ---------------------------------------------------------------------------
//  Decisions d'arret
// ---------------------------------------------------------------------------

function violationGardeFous(verif) {
  const g = verif.garde_fous
  if (!g.tete_inchangee || !g.amont_inchange || !g.zones_intactes) {
    return 'violation du principe 2 detectee (' + g.detail + ')'
  }
  return null
}
function constatsDecision(audit) {
  return audit.constats.filter(function (c) { return c.releve_de !== 'coder' })
}
function constatsCorrigeables(audit) {
  return audit.constats.filter(function (c) {
    return c.releve_de === 'coder' && (c.gravite === 'bloquant' || c.gravite === 'majeur')
  })
}
function batteriesRouges(verif) {
  return verif.batteries.filter(function (b) { return b.code_sortie !== 0 })
}
function batteriesManquantes(verif) {
  return BATTERIES.filter(function (b) {
    return !verif.batteries.some(function (x) { return String(x.commande).indexOf(b) >= 0 })
  })
}
function listerRouges(rouges) {
  return rouges.map(function (b) { return b.commande + ' (code ' + b.code_sortie + ')' }).join(' ; ')
}
function unir(avant, apres, cle) {
  const vus = {}
  return avant.concat(apres).filter(function (x) {
    const k = cle ? x[cle] : x
    if (vus[k]) return false
    vus[k] = true
    return true
  })
}
function noterImplementation(impl) {
  rapport.fichiers_modifies = unir(impl.fichiers_modifies, rapport.fichiers_modifies, 'fichier')
  rapport.surface_documentaire = unir(rapport.surface_documentaire, impl.surface_documentaire, null)
  rapport.commit_propose_non_execute = impl.commit_propose
  rapport.questions_expert = rapport.questions_expert.concat(impl.doutes_expert)
}

// ---------------------------------------------------------------------------
//  Deroulement
// ---------------------------------------------------------------------------

async function derouler() {
  if (BATTERIES.length === 0) {
    return arreter("BATTERIES vide : renseigner les commandes de verification dans .claude/workflows/circuit-technique.js (A ADAPTER)")
  }
  if (!issue) {
    return arreter("argument sans numero d'issue (attendu : '76' ou '76 consigne')")
  }

  phase('Préparation')
  const depot = await agent(
    [
      "Etape mecanique du workflow circuit-technique : releve l'etat du depot, sans rien modifier.",
      INTERDITS,
      "Execute git branch --show-current, git rev-parse HEAD, git rev-parse @{u} (rends 'aucun' en cas d'erreur) et git -c core.quotePath=false status --porcelain --untracked-files=all, et rends les sorties."
    ].join('\n\n'),
    { label: 'etat du depot', agentType: 'audit', effort: 'low', schema: SCHEMA_DEPOT }
  )
  if (!depot) return arreter("l'agent de preparation n'a rien rendu")
  rapport.depot = depot
  if (!depot.arbre_propre) {
    return arreter("arbre de travail non propre au lancement : le diff audite melangerait un travail anterieur (" + depot.status_porcelain + ")")
  }

  // Tour 1
  phase('Implémentation')
  const impl1 = await agent(consigneImplementation(depot.tete, null),
    { label: 'coder #' + issue, agentType: 'coder', schema: SCHEMA_IMPLEMENTATION })
  if (!impl1) return arreter("coder n'a rien rendu")
  const tour1 = { implementation: impl1, verification: null, audit: null }
  rapport.tours.push(tour1)
  noterImplementation(impl1)
  if (impl1.fichiers_modifies.length === 0) return arreter('coder ne declare aucun fichier modifie')

  phase('Vérification')
  const verif1 = await agent(consigneVerification(depot, true),
    { label: 'batteries tour 1', agentType: 'audit', effort: 'low', schema: SCHEMA_VERIFICATION })
  if (!verif1) return arreter("l'agent de verification n'a rien rendu")
  tour1.verification = verif1
  rapport.copie_temporaire = copieValide(verif1.copie_non_suivis) ? verif1.copie_non_suivis.trim() : 'aucun'
  const violation1 = violationGardeFous(verif1)
  if (violation1) return arreter(violation1)
  if (impl1.decision_requise) return arreter('decision requise selon coder : ' + impl1.motif_decision)
  if (verif1.ecart_aux_references) return arreter('ecart aux references : tableau avant / apres a viser par le mainteneur')
  const manquantes1 = batteriesManquantes(verif1)
  if (manquantes1.length > 0) return arreter('verification incomplete, batterie(s) non rapportee(s) : ' + manquantes1.join(' ; '))
  const rouges1 = batteriesRouges(verif1)

  phase('Audit léger')
  const audit1 = await agent(consigneAudit(depot, verif1, null, 1),
    { label: 'audit leger tour 1', agentType: 'audit', schema: SCHEMA_AUDIT })
  if (!audit1) return arreter("audit n'a rien rendu")
  tour1.audit = audit1
  rapport.questions_expert = rapport.questions_expert.concat(audit1.questions_expert)
  if (audit1.contradiction_avec_batteries) return arreter('contradiction entre audit et batteries (principe 3)')
  const decisions1 = constatsDecision(audit1)
  if (decisions1.length > 0) {
    return arreter(decisions1.length + ' constat(s) a trancher hors workflow (' +
      decisions1.map(function (c) { return c.releve_de + ' : ' + c.fichier_ligne }).join(' ; ') + ')')
  }
  const aCorriger = constatsCorrigeables(audit1)
  if (rapport.questions_expert.length > 0) {
    const attente1 = []
    if (rouges1.length > 0) attente1.push('batterie(s) en echec : ' + listerRouges(rouges1))
    if (aCorriger.length > 0) attente1.push(aCorriger.length + ' constat(s) bloquant(s) ou majeur(s) corrigeable(s) non repris')
    if (audit1.conclusion === 'non conforme') attente1.push('audit non conforme')
    if (attente1.length > 0) return arreter('question(s) pour expert et ' + attente1.join(' ; ') + ', sans reprise')
    return terminerAvecQuestions()
  }
  if (aCorriger.length === 0) {
    if (rouges1.length > 0) return arreter('batterie(s) en echec sans constat corrigeable par coder : ' + listerRouges(rouges1))
    if (audit1.conclusion === 'non conforme') return arreter('audit non conforme sans constat bloquant ou majeur corrigeable par coder')
    rapport.statut = 'termine'
    log('Audit leger : ' + audit1.conclusion + ', aucune reprise necessaire')
    return rapport
  }
  if (!instantaneValide(verif1.instantane) && !copieValide(verif1.copie_non_suivis)) {
    return arreter("ni instantane ni copie des fichiers non suivis au tour 1 : l'audit de la reprise ne pourrait pas isoler le diff de la correction")
  }

  // Tour 2 : reprise unique (principe 4)
  phase('Reprise')
  const aTransmettre = { constats: aCorriger, batteries_en_echec: rouges1 }
  const impl2 = await agent(consigneImplementation(depot.tete, aTransmettre),
    { label: 'reprise coder #' + issue, agentType: 'coder', schema: SCHEMA_IMPLEMENTATION })
  if (!impl2) return arreter("coder n'a rien rendu a la reprise")
  const tour2 = { implementation: impl2, verification: null, audit: null }
  rapport.tours.push(tour2)
  noterImplementation(impl2)
  if (impl2.fichiers_modifies.length === 0) return arreter('reprise sans fichier modifie : constats du tour 1 non corriges')

  phase('Vérification de la reprise')
  const verif2 = await agent(consigneVerification(depot, false),
    { label: 'batteries tour 2', agentType: 'audit', effort: 'low', schema: SCHEMA_VERIFICATION })
  if (!verif2) return arreter("l'agent de verification n'a rien rendu a la reprise")
  tour2.verification = verif2
  const violation2 = violationGardeFous(verif2)
  if (violation2) return arreter(violation2)
  if (impl2.decision_requise) return arreter('decision requise selon coder a la reprise : ' + impl2.motif_decision)
  if (verif2.ecart_aux_references) return arreter('ecart aux references apres la reprise : tableau avant / apres a viser')
  const manquantes2 = batteriesManquantes(verif2)
  if (manquantes2.length > 0) return arreter('verification incomplete a la reprise, batterie(s) non rapportee(s) : ' + manquantes2.join(' ; '))

  phase('Audit de la reprise')
  const audit2 = await agent(consigneAudit(depot, verif2, verif1, 2, aTransmettre),
    { label: 'audit leger tour 2', agentType: 'audit', schema: SCHEMA_AUDIT })
  if (!audit2) return arreter("audit n'a rien rendu a la reprise")
  tour2.audit = audit2
  rapport.questions_expert = rapport.questions_expert.concat(audit2.questions_expert)
  if (audit2.contradiction_avec_batteries) return arreterReprise('contradiction entre audit et batteries apres la reprise (principe 3)')
  if (constatsDecision(audit2).length > 0) return arreterReprise('constat(s) a trancher hors workflow apres la reprise')
  if (constatsCorrigeables(audit2).length > 0) return arreterReprise('constat bloquant ou majeur apres la reprise unique (principe 4)')
  const rouges2 = batteriesRouges(verif2)
  if (rouges2.length > 0) return arreterReprise('batterie(s) en echec apres la reprise unique : ' + listerRouges(rouges2))
  if (audit2.conclusion === 'non conforme') return arreterReprise('audit de la reprise non conforme (principe 4)')
  if (rapport.questions_expert.length > 0) return terminerAvecQuestions()
  rapport.statut = 'termine'
  log('Audit de la reprise : ' + audit2.conclusion)
  return rapport
}

return await derouler()
