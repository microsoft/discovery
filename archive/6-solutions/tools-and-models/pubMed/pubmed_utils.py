"""
PubMed Utilities Module

A comprehensive utility module for accessing PubMed and PMC databases,
providing enhanced functionality for literature search, metadata extraction,
and full-text article downloads.

This module provides high-level functions for:
- Enhanced metadata extraction with open access detection
- PMC integration for full-text article downloads
- PubMed-to-PMC linking and open access status checking
- Complete research article download workflows

Author: Microsoft Discovery PubMed Agent
Date: October 2025
"""

import json
import os
import time
import ssl
from typing import List, Dict, Optional, Any
from xml.etree import ElementTree as ET

from pymed import PubMed
from Bio import Entrez

# Configure SSL to handle certificate issues in containers
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass


class PubMedUtils:
    """
    Utility class for PubMed and PMC operations with enhanced functionality.
    """
    
    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize PubMedUtils with authentication credentials.
        
        Args:
            email: Email address for NCBI API (required)
            api_key: NCBI API key for higher rate limits (optional)
        """
        # Get credentials from environment variables with fallbacks
        self.email = email or os.getenv("PUBMED_EMAIL", "your_email@example.com")
        self.api_key = api_key or os.getenv("PUBMED_API_KEY")
        
        # Initialize PyMed
        self.pubmed = PubMed(tool="PubMedAgent", email=self.email)
        
        # Set up Entrez
        Entrez.email = self.email
        if self.api_key and self.api_key.strip():
            Entrez.api_key = self.api_key
    
    def get_enhanced_article_metadata(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Get article metadata with open access status and links.
        
        Args:
            query: PubMed search query
            max_results: Maximum number of results to return
            
        Returns:
            List of dictionaries containing enhanced article metadata
        """
        results = self.pubmed.query(query, max_results=max_results)
        enhanced_articles = []
        
        for article in results:
            # Basic metadata from PyMed
            article_data = {
                "title": article.title,
                "abstract": article.abstract,
                "authors": [str(author) for author in article.authors] if article.authors else [],
                "journal": article.journal,
                "publication_date": str(article.publication_date) if article.publication_date else None,
                "pubmed_id": article.pubmed_id,
                "doi": article.doi,
                "keywords": article.keywords
            }
            
            # Check for open access status using PMID
            if article.pubmed_id:
                try:
                    # Link to PMC
                    handle = Entrez.elink(dbfrom="pubmed", id=article.pubmed_id, linkname="pubmed_pmc")
                    link_results = Entrez.read(handle)
                    handle.close()
                    
                    pmc_ids = []
                    if link_results and link_results[0].get("LinkSetDb"):
                        for link_db in link_results[0]["LinkSetDb"]:
                            if link_db["LinkName"] == "pubmed_pmc":
                                pmc_ids = [link["Id"] for link in link_db["Link"]]
                    
                    article_data.update({
                        "open_access": {
                            "has_pmc": len(pmc_ids) > 0,
                            "pmc_ids": [f"PMC{pmc_id}" for pmc_id in pmc_ids],
                            "pmc_urls": [f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/" for pmc_id in pmc_ids]
                        }
                    })
                    
                    # Add publisher links
                    if article.doi:
                        article_data["publisher_url"] = f"https://doi.org/{article.doi}"
                    
                except Exception as e:
                    print(f"Error checking open access for PMID {article.pubmed_id}: {str(e)}")
                    article_data["open_access"] = {"has_pmc": False, "pmc_ids": [], "pmc_urls": []}
            
            enhanced_articles.append(article_data)
        
        return enhanced_articles
    
    def get_pmc_articles(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for open access articles in PMC and get full-text.
        
        Args:
            query: PMC search query
            max_results: Maximum number of results to return
            
        Returns:
            List of dictionaries containing PMC articles with full-text
        """
        # Search PMC for open access articles
        handle = Entrez.esearch(db="pmc", term=f"{query} AND open access[filter]", retmax=max_results)
        search_results = Entrez.read(handle)
        handle.close()
        
        pmc_ids = search_results["IdList"]
        articles_with_fulltext = []
        
        for pmc_id in pmc_ids:
            try:
                # Get article metadata from PMC
                handle = Entrez.efetch(db="pmc", id=pmc_id, rettype="xml", retmode="text")
                xml_content = handle.read()
                handle.close()
                
                # Parse XML to extract metadata and check for full-text availability
                root = ET.fromstring(xml_content)
                
                # Extract basic metadata
                title_elem = root.find(".//article-title")
                title = title_elem.text if title_elem is not None else "No title"
                
                # Check if full-text is available
                body_elem = root.find(".//body")
                has_fulltext = body_elem is not None
                
                # Get PMC URL
                pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/"
                
                article_data = {
                    "pmc_id": f"PMC{pmc_id}",
                    "title": title,
                    "pmc_url": pmc_url,
                    "has_fulltext": has_fulltext,
                    "fulltext_xml": xml_content if has_fulltext else None
                }
                
                articles_with_fulltext.append(article_data)
                
            except Exception as e:
                print(f"Error processing PMC{pmc_id}: {str(e)}")
                continue
        
        return articles_with_fulltext
    
    def link_pubmed_to_pmc(self, pmid: str) -> List[str]:
        """
        Find PMC articles linked to a PubMed ID.
        
        Args:
            pmid: PubMed ID (cleaned string)
            
        Returns:
            List of PMC IDs linked to the PubMed article
        """
        try:
            # Clean PMID - ensure it's a single ID without newlines
            clean_pmid = str(pmid).strip()
            if '\n' in clean_pmid:
                clean_pmid = clean_pmid.split('\n')[0].strip()
            
            handle = Entrez.elink(dbfrom="pubmed", id=clean_pmid, linkname="pubmed_pmc")
            link_results = Entrez.read(handle)
            handle.close()
            
            pmc_ids = []
            if link_results and link_results[0].get("LinkSetDb"):
                for link_db in link_results[0]["LinkSetDb"]:
                    if link_db["LinkName"] == "pubmed_pmc":
                        pmc_ids = [link["Id"] for link in link_db["Link"]]
            
            return pmc_ids
        except Exception as e:
            print(f"Error linking PMID {pmid} to PMC: {str(e)}")
            return []
    
    def check_open_access_status(self, pmid: str) -> Dict[str, Any]:
        """
        Check if a PubMed article has open access version.
        
        Args:
            pmid: PubMed ID
            
        Returns:
            Dictionary with open access status and PMC information
        """
        pmc_ids = self.link_pubmed_to_pmc(pmid)
        
        if pmc_ids:
            return {
                "has_open_access": True,
                "pmc_ids": [f"PMC{pmc_id}" for pmc_id in pmc_ids],
                "pmc_urls": [f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/" for pmc_id in pmc_ids]
            }
        else:
            return {
                "has_open_access": False,
                "pmc_ids": [],
                "pmc_urls": []
            }
    
    def download_research_articles(self, query, max_results=10, output_dir='/output'):
        """
        Complete workflow: search PubMed, check PMC for open access, download full-text when available
        
        Args:
            query: Search query string
            max_results: Maximum number of articles to process
            output_dir: Directory to save downloaded files (default: '/output')
            
        Returns:
            Dict with summary of results and downloaded files
        """
        # Validate output_dir is provided
        if not output_dir:
            raise ValueError("output_dir is required. Pass the output directory from dataHandlingContext.")
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"Starting research article download for query: {query}")
        
        # Search PubMed
        results = list(self.pubmed.query(query, max_results=max_results))
        downloaded_articles = []
        
        for i, article in enumerate(results, 1):
            print(f"Processing article {i}/{len(results)}: {article.title[:50]}...")
            
            article_data = {
                "pmid": article.pubmed_id,
                "title": article.title,
                "abstract": article.abstract,
                "journal": article.journal,
                "publication_date": str(article.publication_date) if article.publication_date else None,
                "authors": [str(author) for author in article.authors] if article.authors else [],
                "doi": article.doi,
                "download_status": "failed",
                "download_type": "none",
                "files_created": []
            }
            
            # Check for PMC open access version
            if article.pubmed_id:
                # Ensure PMID is a string and clean
                pmid = str(article.pubmed_id).strip()
                if '\n' in pmid:
                    pmid = pmid.split('\n')[0].strip()  # Take only the first PMID if multiple
                
                try:
                    pmc_ids = self.link_pubmed_to_pmc(pmid)
                    
                    # Download full-text from PMC if available
                    if pmc_ids:
                        pmc_id = pmc_ids[0]  # Use first PMC ID
                        print(f"  Found PMC version: PMC{pmc_id}")
                        
                        try:
                            # Download XML full-text
                            handle = Entrez.efetch(db="pmc", id=pmc_id, rettype="xml", retmode="text")
                            xml_content = handle.read()
                            handle.close()
                            
                            # Save XML file
                            xml_filename = f"{output_dir}/article_{i}_PMC{pmc_id}_fulltext.xml"
                            with open(xml_filename, "w", encoding="utf-8") as f:
                                f.write(xml_content)
                            
                            # Extract and save plain text
                            try:
                                root = ET.fromstring(xml_content)
                                text_content = self._extract_text_from_xml(root)
                                
                                # Save as readable text file
                                txt_filename = f"{output_dir}/article_{i}_PMC{pmc_id}_readable.txt"
                                with open(txt_filename, "w", encoding="utf-8") as f:
                                    f.write(text_content)
                                
                                article_data.update({
                                    "download_status": "success",
                                    "download_type": "pmc_fulltext",
                                    "pmc_id": f"PMC{pmc_id}",
                                    "pmc_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/",
                                    "files_created": [xml_filename, txt_filename]
                                })
                                
                                print(f"  ✓ Downloaded full-text: {txt_filename}")
                                
                            except ET.ParseError:
                                print(f"  ! Could not parse XML for PMC{pmc_id}")
                                article_data["download_status"] = "xml_parse_error"
                            
                        except Exception as e:
                            print(f"  ! Error downloading PMC{pmc_id}: {str(e)}")
                            article_data["download_status"] = "pmc_download_error"
                    
                    else:
                        print(f"  No PMC version found - subscription only")
                        article_data["download_status"] = "no_open_access"
                        
                        # Save metadata only with clean filename
                        metadata_filename = f"{output_dir}/article_{i}_PMID{pmid}_metadata.json"
                        metadata = {
                            "title": article_data["title"],
                            "abstract": article_data["abstract"],
                            "authors": article_data["authors"],
                            "journal": article_data["journal"],
                            "doi": article_data["doi"],
                            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                            "publisher_url": f"https://doi.org/{article.doi}" if article.doi else None
                        }
                        
                        with open(metadata_filename, "w", encoding="utf-8") as f:
                            json.dump(metadata, f, indent=2)
                        
                        article_data["files_created"] = [metadata_filename]
                        print(f"  ✓ Saved metadata: {metadata_filename}")
                
                except Exception as e:
                    print(f"  ! Error processing PMID {pmid}: {str(e)}")
                    article_data["download_status"] = "processing_error"
            
            downloaded_articles.append(article_data)
            
            # Rate limiting - be nice to NCBI servers
            time.sleep(0.5)
        
        # Create summary report
        summary = {
            "search_query": query,
            "search_date": time.strftime("%Y-%m-%d"),
            "total_articles_found": len(downloaded_articles),
            "successful_downloads": len([a for a in downloaded_articles if a["download_status"] == "success"]),
            "open_access_available": len([a for a in downloaded_articles if a["download_type"] == "pmc_fulltext"]),
            "subscription_only": len([a for a in downloaded_articles if a["download_status"] == "no_open_access"]),
            "articles": downloaded_articles
        }
        
        # Save comprehensive results
        summary_filename = f"{output_dir}/research_download_summary.json"
        with open(summary_filename, "w") as f:
            json.dump(summary, f, indent=2)
        
        # Create download report
        self._create_download_report(summary, downloaded_articles, output_dir)
        
        print(f"\nDownload complete! Created {len([f for a in downloaded_articles for f in a.get('files_created', [])])} files")
        
        return summary
    
    def _extract_text_from_xml(self, root: ET.Element) -> str:
        """
        Extract readable text content from PMC XML.
        
        Args:
            root: XML root element
            
        Returns:
            Formatted text content
        """
        text_content = []
        
        # Title
        title_elem = root.find(".//article-title")
        if title_elem is not None:
            text_content.append(f"TITLE: {title_elem.text}\n")
        
        # Abstract
        abstract_elem = root.find(".//abstract")
        if abstract_elem is not None:
            abstract_text = " ".join([elem.text or "" for elem in abstract_elem.iter() if elem.text])
            text_content.append(f"ABSTRACT: {abstract_text}\n")
        
        # Body text
        body_elem = root.find(".//body")
        if body_elem is not None:
            body_text = " ".join([elem.text or "" for elem in body_elem.iter() if elem.text])
            text_content.append(f"FULL TEXT: {body_text}\n")
        
        return "\n".join(text_content)
    
    def _create_download_report(self, summary: Dict[str, Any], articles: List[Dict[str, Any]], output_dir: str):
        """
        Create a human-readable download report.
        
        Args:
            summary: Summary statistics
            articles: List of processed articles
            output_dir: Output directory
        """
        report_lines = [
            "Research Article Download Report",
            "=" * 40,
            f"Search Query: {summary['search_query']}",
            f"Date: {summary['search_date']}",
            f"Total Articles: {summary['total_articles_found']}",
            f"Successful Downloads: {summary['successful_downloads']}",
            f"Open Access Available: {summary['open_access_available']}",
            f"Subscription Only: {summary['subscription_only']}",
            "",
            "Downloaded Files:",
            "-" * 20
        ]
        
        for i, article in enumerate(articles, 1):
            report_lines.append(f"{i}. {article['title'][:60]}...")
            report_lines.append(f"   Status: {article['download_status']}")
            for filename in article.get('files_created', []):
                report_lines.append(f"   File: {filename}")
            report_lines.append("")
        
        report_filename = f"{output_dir}/download_report.txt"
        with open(report_filename, "w") as f:
            f.write("\n".join(report_lines))


# Convenience functions for direct usage
def search_and_download(query: str, max_results: int = 10, email: str = None, api_key: str = None, output_dir: str = '/output') -> Dict[str, Any]:
    """
    Convenience function to search and download articles in one call.
    
    Args:
        query: PubMed search query
        max_results: Maximum number of results
        email: Email for NCBI API
        api_key: API key for NCBI
        output_dir: Directory to save downloaded files (default: '/output')
        
    Returns:
        Summary of download results
    """
    utils = PubMedUtils(email=email, api_key=api_key)
    return utils.download_research_articles(query, max_results, output_dir=output_dir)


def get_metadata_with_open_access(query: str, max_results: int = 20, email: str = None, api_key: str = None) -> List[Dict[str, Any]]:
    """
    Convenience function to get enhanced metadata with open access detection.
    
    Args:
        query: PubMed search query
        max_results: Maximum number of results
        email: Email for NCBI API
        api_key: API key for NCBI
        
    Returns:
        List of enhanced article metadata
    """
    utils = PubMedUtils(email=email, api_key=api_key)
    return utils.get_enhanced_article_metadata(query, max_results)


def search_pmc_articles(query: str, max_results: int = 10, email: str = None, api_key: str = None) -> List[Dict[str, Any]]:
    """
    Convenience function to search PMC for open access articles.
    
    Args:
        query: PMC search query
        max_results: Maximum number of results
        email: Email for NCBI API
        api_key: API key for NCBI
        
    Returns:
        List of PMC articles with full-text
    """
    utils = PubMedUtils(email=email, api_key=api_key)
    return utils.get_pmc_articles(query, max_results)