"""
Classe abstraite définissant l'interface commune pour tous les parsers de documents.
Chaque parser (PDF, DOCX) doit implémenter la méthode `parse` qui retourne
une structure uniforme représentant le document avec sa hiérarchie de titres.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class Section:
    """
    Représente une section du document avec son titre, son niveau hiérarchique
    et son contenu textuel.

    Attributes:
        title: Le texte du titre de la section
        level: Le niveau hiérarchique (1 = titre principal, 2 = sous-titre, etc.)
        content: Le contenu textuel de la section (paragraphes sous ce titre)
    """
    title: str
    level: int
    content: str = ""


@dataclass
class ParsedDocument:
    """
    Représente un document entièrement parsé, prêt à être résumé.

    Attributes:
        title: Le titre principal du document
        sections: Liste ordonnée de toutes les sections avec leur hiérarchie
        raw_text: Le texte brut complet du document (pour le résumé)
    """
    title: str = ""
    sections: List[Section] = field(default_factory=list)
    raw_text: str = ""


class BaseParser(ABC):
    """
    Interface abstraite pour les parsers de documents.
    Chaque format de fichier (PDF, DOCX) doit fournir sa propre implémentation.
    """

    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        """
        Parse un fichier et retourne un ParsedDocument contenant la structure
        hiérarchique des titres et le contenu de chaque section.

        Args:
            file_path: Chemin absolu vers le fichier à parser

        Returns:
            ParsedDocument avec les sections et la hiérarchie des titres
        """
        pass
