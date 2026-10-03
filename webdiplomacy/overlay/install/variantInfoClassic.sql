-- Sur une base neuve, wD_VariantInfo est vide : l'amont ne la remplit que par une action
-- d'administration (« Update wD_VariantInfo »), et la création d'une partie contre les
-- bots échoue sans cette ligne. Valeurs produites par cette action pour la variante Classic.
INSERT INTO wD_VariantInfo
  (variantID, mapID, supplyCenterTarget, supplyCenterCount, countryCount, name, fullName, description, author, countriesList)
VALUES
  (1, 1, 18, 34, 7, 'Classic', 'Classic', 'The standard Diplomacy map of Europe.', 'Avalon Hill',
   'England,France,Italy,Germany,Austria,Turkey,Russia');
