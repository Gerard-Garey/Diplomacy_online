<?php
// Crée une partie dont les sept puissances sont tenues par les comptes de type bot (#12).
// Usage (ligne de commande seulement) :
//   docker exec -e XDEBUG_MODE=off webdiplomacy-php-fpm-1 php /application/gamecreateBotsOnly.php <nom>
// Sortie : dernière ligne « gameID=<n> » et code 0 ; sinon message sur stderr et code non nul
// (2 : mauvais usage, avant tout accès à la base ; 1 : échec, transaction annulée).
//
// Reprend botgamecreate.php (création de la partie, des membres, puis processTime et processHint)
// avec trois différences :
// - playerTypes='Members' : gamemaster/game.php déclare nulle toute partie d'un autre type dont
//   les joueurs actifs sont tous des bots ;
// - missingPlayerPolicy='Wait' : avec 'Members' la logique d'absence redevient active ; 'Wait'
//   laisse la partie hors du traitement tant qu'un joueur actif n'a pas d'ordres complets ;
// - les sept comptes de type bot, par id croissant, sur les pays 1 à 7, sans créateur humain.

// Première instruction exécutable : rien n'est chargé ni lu sous un autre SAPI.
if( php_sapi_name() !== 'cli' )
{
	http_response_code(403);
	die("This script must only be run from the command line");
}

// Le nom est validé avant header.php : un mauvais usage n'ouvre pas de connexion à la base.
// Jeu de caractères restreint, pour que le nom passe tel quel dans le SQL de processGame::create
// (qui tronque à 50 caractères) ; \z et non $, qui laisserait passer un saut de ligne final.
// L'amont reconnaît une partie bac à sable par name LIKE 'SB_%' (« _ » y est un joker, la
// collation ignore la casse) : gamemaster/backgroundTasks.php repousse alors son processTime
// à 2000000000, et elle ne se résout plus jamais. Tout nom « SB » suivi d'un caractère est refusé.
$nom = $argc == 2 ? $argv[1] : '';
if( !preg_match('/^[A-Za-z0-9][A-Za-z0-9_.-]{0,49}\z/', $nom) || preg_match('/^SB./i', $nom) )
{
	fwrite(STDERR, "Usage : php gamecreateBotsOnly.php <nom>\n".
		"  <nom> : 1 à 50 caractères parmi A-Z a-z 0-9 _ . - ; premier caractère alphanumérique ;\n".
		"          les noms commençant par « SB » (casse indifférente : SB_x, SBtest, Sbires) sont refusés\n");
	exit(2);
}

// L'amont arrête le script par die() sur ses propres erreurs (global/error.php, libHTML::error),
// avec le code 0 : sans « gameID » imprimé, le code de sortie est forcé à 1.
$termine = false;
register_shutdown_function(function() {
	global $termine;
	if( !$termine )
	{
		fwrite(STDERR, "\ngamecreateBotsOnly : arrêt avant la fin, aucune partie annoncée.\n");
		exit(1);
	}
});

chdir(__DIR__);
require_once('header.php');
// RUNNINGFROMCLI n'est pas défini : objects/database.php imprimerait chaque requête.

ob_end_flush(); // Tampon ouvert par header.php, que seul libHTML::footer() vide.
// Ne pas le retirer sans réexamen : il ferme le seul tampon, donc un libHTML::notice pendant la création lève un E_NOTICE (ob_clean sans tampon, lib/html.php) et error_handler fait le ROLLBACK.
ini_set('memory_limit',"200M"); // header.php vient de les fixer à 32M et 4 s.
ini_set('max_execution_time','300');

require_once(l_r('gamemaster/game.php'));

global $DB, $Redis, $Misc, $Game; // processMember::create lit $Game au niveau global.

try
{
	if( $Misc->Panic )
		throw new Exception("création de partie désactivée (wD_Misc.Panic)");

	list($dejaPris) = $DB->sql_row("SELECT COUNT(id) FROM wD_Games WHERE name='".$nom."'");
	if( $dejaPris > 0 )
		throw new Exception("le nom « ".$nom." » est déjà pris"); // processGame::create le suffixerait en silence

	$botIDs = array();
	$tabl = $DB->sql_tabl("SELECT id FROM wD_Users WHERE type LIKE '%bot%' ORDER BY id");
	while( list($botID) = $DB->tabl_row($tabl) )
		$botIDs[] = (int)$botID;
	if( count($botIDs) != 7 )
		throw new Exception("sept comptes de type bot attendus, ".count($botIDs)." trouvé(s)");

	// Jusqu'ici, des lectures seulement. Variante 1 (Classic), mise 5, 'Unranked', phases de 3 jours,
	// presse 'Regular' : comme botgamecreate.php.
	$phaseMinutes = 3*24*60;
	$Game = processGame::create(1,$nom,'',5,'Unranked', $phaseMinutes, -1, $phaseMinutes, -1, 60,'No','Regular','Wait','draw-votes-public',0,4,'Members');

	$countryID = 1;
	foreach($botIDs as $botID)
		processMember::create($botID, 5, $countryID++);

	list($membres, $pays) = $DB->sql_row("SELECT COUNT(*), COUNT(DISTINCT countryID) FROM wD_Members WHERE gameID = ".$Game->id." AND countryID BETWEEN 1 AND 7");
	if( $membres != 7 || $pays != 7 )
		throw new Exception("membres créés : ".$membres." sur ".$pays." pays, sept attendus");

	// Get the game started straight away
	$DB->sql_put('UPDATE wD_Games SET processTime = ' . time() . ' WHERE id = ' . $Game->id);
	$DB->sql_put("COMMIT"); // Usually done in libHTML::footer()
}
catch(Throwable $e)
{
	if( is_object($DB) ) $DB->sql_put("ROLLBACK");
	$termine = true; // le code de sortie est donné ici
	fwrite(STDERR, "gamecreateBotsOnly : échec, rien n'est créé : ".$e->getMessage()."\n");
	exit(1);
}

// Après le COMMIT : le gamemaster ne reçoit pas l'indice d'une partie encore invisible pour lui.
// L'indice n'est qu'un accélérateur (processTime est déjà échu) : son échec n'annule pas la partie.
try
{
	$Redis->append('processHint',','.$Game->id);
}
catch(Throwable $e)
{
	fwrite(STDERR, "gamecreateBotsOnly : processHint non écrit (".$e->getMessage().") ; la partie démarrera au prochain cycle du gamemaster.\n");
}

$termine = true;
print "gameID=".$Game->id."\n";
exit(0);
