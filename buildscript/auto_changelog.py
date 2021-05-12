#!/usr/bin/env python3

import click
import json
import logging
import re
import os
import requests

from bs4 import BeautifulSoup
from github import Github, UnknownObjectException
try:
    from pydriller import RepositoryMining
except:
    from pydriller import Repository as RepositoryMining
logging.basicConfig(level=logging.INFO)


class ReleaseNotesBuilder(object):
    """ NOTES
    ## package documentaion
    https://gitpython.readthedocs.io/en/stable/tutorial.html  -- base class used in pydriller
    https://github.com/ishepard/pydriller                     -- analysze git repo
    https://github.com/PyGithub/PyGithub                      -- fetch github data/metadata
    https://click.palletsprojects.com/en/7.x/                 -- cli options

    ## install requirments
    'pip install github pydriller click'
    """
    def __init__(self, github_token=None, github_user='OasisLMF'):
        self.github_token = github_token
        self.github_user = github_user
        self.logger = logging.getLogger()


    def _get_commit_refs(self, repo_url, from_tag, to_tag):
        """ find all commits between the two tags [`tag_start` .. `tag_end`]
            Extract any text from the commit message showing a github tag reference `#{number}`
            and return a set of ints

            until checked with the GitHub API, its not known if these refs are to pull requests, issues or just typos

            commit_list = ['#772', '#774', .. , '#811']
            return = {772, 774, .. ,811}
        """
        self.logger.info("Fetching commits between tags {}...{} ".format(from_tag, to_tag))

        repo = RepositoryMining(repo_url, from_tag=from_tag, to_tag=to_tag)
        commit_list = [re.findall(r'#\d+', commit.msg) for commit in repo.traverse_commits()]
        commit_list = sum(commit_list, [])
        return set(map(lambda cm: int(cm[1:]), commit_list))


    def _get_github_pull_requests(self, github, commit_refs):
        """ All pull requests have issues but not all issue have pull requests

            calling Issue(id).as_pull_request() will return the PR details 'if it exisits'
            otherwise will rasie 'UnknownObjectException' 404

            This filters out non-PR references
        """
        pull_requeusts = []
        for ref in commit_refs:
            try:
                pull_requeusts.append(github.get_pull(ref))
            except UnknownObjectException:
                pass

        self.logger.info("Filtered github refereces to Pull Requests: {}".format([pr.number for pr in pull_requeusts]))
        return pull_requeusts


    def _get_linked_issues(self, pr_number, repo_url):
        """ there is no direct way to find which issues are linked to a PR via the github API (yet)
            for the moment this func scraps github using `BeautifulSoup`
        """
        r = requests.get(f"{repo_url}/pull/{pr_number}")
        soup = BeautifulSoup(r.text, 'html.parser')
        issueForm = soup.find("form", { "aria-label": re.compile('Link issues')})
        issue_urls_found = [ re.findall(r'\d+', i["href"]) for i in issueForm.find_all("a")]
        issue_refs = sum(issue_urls_found, [])

        self.logger.info("PR-{} linked issues: {}".format(pr_number, issue_refs))
        return set(map(int, issue_refs))


    def _get_tag(self, repo_name, idx=0):
        resp = requests.get(f'https://api.github.com/repos/{self.github_user}/{repo_name}/tags')
        resp.raise_for_status()
        if resp.ok:
            tag_data = json.loads(resp.text)
            return tag_data[idx]['name']

    def _get_all_tags(self, repo_name):
        resp = requests.get(f'https://api.github.com/repos/{self.github_user}/{repo_name}/tags')
        resp.raise_for_status()
        if resp.ok:
            tag_data = json.loads(resp.text)
            return [tag.get('name')for tag in tag_data]


    def load_data(self, repo_name, tag_from=None, tag_to=None):
        """
        {
            'name': 'OasisLMF',
            'url': 'https://github.com/OasisLMF/OasisLMF'
            'tag_from': '1.15.0',
            'tag_to': '1.16.0',
            'pull_requests': [
                {
                    'id': 772,
                    'pull_request': PullRequest(title="Fix/771 fix genbash", number=772),
                    'linked_issues': [
                        Issue(title="genbash, fmpy calls --create-financial-structure-files when running GUL only ", number=771)
                    ]
                },
                {
                    'id': 774,
                    'pull_request': PullRequest(title="use il summary map even for gul if present", number=774),
                    'linked_issues': [
                        Issue(title="Insured loss summary terms when running ground up only", number=777)
                    ]
                },
                        ... etc ...
                {
                    'id': 815,
                    'pull_request': PullRequest(title="Fix/dev package requirements", number=815),
                    'linked_issues': []
                }
            ]
        }
        """
        # Load repository data
        github = Github(login_or_token=self.github_token).get_repo(f'{self.github_user}/{repo_name}')

        # Search commits for PR references
        repo_url = f'https://github.com/{self.github_user}/{repo_name}'
        all_refs = self._get_commit_refs(repo_url, tag_from, tag_to)
        pull_reqs = self._get_github_pull_requests(github, all_refs)

        pull_requests = list()
        for pr in pull_reqs:
            linked_issues = self._get_linked_issues(pr.number, repo_url)
            pull_requests.append({
                "id": pr.number,
                "pull_request": pr,
                "linked_issues": [github.get_issue(ref) for ref in linked_issues]
            })

        self.logger.info("{} - Github data fetch complete".format(repo_name))
        return {
            "name": repo_name,
            "url": repo_url,
            "tag_from": tag_from,
            "tag_to": tag_to,
            "pull_requests": pull_requests
        }


    def create_changelog(self, github_data):
        changelog_lines = []
        changelog_lines.append('`{}`_'.format(github_data['tag_to']))
        changelog_lines.append(' ---------')

        # Check that at least one Pull request has been picked up
        for pr in github_data['pull_requests']:
            num_issues_linked = len(pr['linked_issues'])
            if num_issues_linked < 1:
                # Case 0: PR has no linked issues
                changelog_lines.append("* [#{}]({}) - {}".format(
                    pr['id'],
                    pr['pull_request'].html_url,
                    pr['pull_request'].title
                ))
            elif num_issues_linked == 1:
                # Case 1: PR has a single linked issue
                changelog_lines.append("* [#{}]({}) - {}".format(
                    pr['linked_issues'][0].number,
                    pr['pull_request'].html_url,
                    pr['linked_issues'][0].title,
                ))
            else:
            # Case 2: PR has multiple linked issues
                changelog_lines.append("* [{}]({}) - {}".format(
                    ', '.join([f'#{issue.number}' for issue in  pr['linked_issues']]),
                    pr['pull_request'].html_url,
                    pr['pull_request'].title
                ))

        changelog_lines.append(".. _`{}`:  {}/compare/{}...{}".format(
            github_data['tag_to'],
            github_data["url"],
            github_data['tag_from'],
            github_data['tag_to'],
        ))
        changelog_lines.append("")

        changelog_lines = list(map(lambda l: l + "\n", changelog_lines))
        self.logger.info("CHANGELOG OUTPUT: \n" +  "".join(changelog_lines))
        return changelog_lines

    def release_header(self, tag_platform=None, tag_oasislmf=None, tag_oasisui=None, tag_ktools=None):
        """
        """
        t_plat = tag_platform if tag_platform else self._get_tag('OasisPlatform')
        t_lmf = tag_oasislmf if tag_oasislmf else self._get_tag('OasisLMF')
        t_ktools = tag_ktools if tag_ktools else self._get_tag('ktools')
        t_ui = tag_oasisui if tag_oasisui else self._get_tag('OasisUI')

        plat_header = []
        plat_header.append('## Docker Images (Platform)\n')
        plat_header.append(f'* [coreoasis/api_server:{t_plat}](https://hub.docker.com/r/coreoasis/api_server/tags?name={t_plat})\n')
        plat_header.append(f'* [coreoasis/model_worker:{t_plat}](https://hub.docker.com/r/coreoasis/model_worker/tags?name={t_plat})\n')
        plat_header.append(f'* [coreoasis/model_worker:{t_plat}-debian](https://hub.docker.com/r/coreoasis/model_worker/tags?name={t_plat}-debian)\n')
        plat_header.append(f'* [coreoasis/piwind_worker:{t_plat}](https://hub.docker.com/r/coreoasis/piwind_worker/tags?name={t_plat})\n')
        plat_header.append('## Docker Images (User Interface)\n')
        plat_header.append(f'* [coreoasis/oasisui_app:{t_ui}](https://hub.docker.com/r/coreoasis/oasisui_app/tags?name={t_ui})\n')
        plat_header.append(f'* [coreoasis/oasisui_proxy:{t_ui}](https://hub.docker.com/r/coreoasis/oasisui_proxy/tags?name={t_ui})\n')
        plat_header.append('## Components\n')
        plat_header.append(f'* [oasislmf {t_lmf}](https://github.com/OasisLMF/OasisLMF/releases/tag/{t_lmf})\n')
        plat_header.append(f'* [ktools {t_ktools}](https://github.com/OasisLMF/ktools/releases/tag/{t_ktools})\n')
        plat_header.append(f'* [Oasis UI {t_ui}](https://github.com/OasisLMF/OasisUI/releases/tag/{t_ui})\n')
        plat_header.append('\n')
        return plat_header


    def extract_pr_content(self, github_data):
        """
        """
        START = '<!--start_release_notes-->\r\n'
        END = '<!--end_release_notes-->'
        release_note_content = []
        has_content = False

        if github_data:
            for pr in github_data.get('pull_requests'):
                pr_body = pr['pull_request'].body

                idx_start = pr_body.find(START)
                idx_end = pr_body.rfind(END)
                if (idx_start == -1 or idx_end == -1):
                    # skip PR if release note tags are missing
                    continue

                release_desc = pr_body[idx_start+len(START):idx_end]
                if len(release_desc.strip()) < 1:
                    # skip PR if tags contain an empty string
                    continue
                release_note_content.append(release_desc)
                has_content = True

        return has_content, release_note_content



    def create_release_notes(self,  platform_data={}, oasislmf_data={}, ktools_data={}, oasisui_data={}):
        """ Main release notes page (Only used for OasisPlatform)
        """
        release_notes = self.release_header(
            tag_platform=platform_data.get('tag_to'),
            tag_oasislmf=oasislmf_data.get('tag_to'),
            tag_ktools=ktools_data.get('tag_to'),
            tag_oasisui=oasisui_data.get('tag_to'),
        )
        for repo in [platform_data, oasislmf_data, ktools_data]:
            has_notes, pr_notes = self.extract_pr_content(repo)
            if has_notes:
                release_notes.append('## {} Notes\r\n'.format(repo.get('name')))
                release_notes += pr_notes + ['\r\n']

        self.logger.info("RELEASE NOTES OUTPUT: \n" +  "".join(release_notes))
        return release_notes



@click.group()
def cli():
    pass


@cli.command()
@click.option('--repo',         type=click.Choice(['ktools', 'OasisLMF', 'OasisPlatform', 'OasisUI'], case_sensitive=True), required=True)
@click.option('--output-path',  type=click.Path(exists=False), default='./CHANGELOG.rst', help='changelog output path')
@click.option('--from-tag',     required=True, help='Github tag to track changes from' )
@click.option('--to-tag',       required=True, help='Github tag to track changes to')
@click.option('--github-token', default=None, help='Github OAuth token')
def build_changelog(repo, from_tag, to_tag, github_token, output_path):
    # Setup
    logger = logging.getLogger()
    noteBuilder = ReleaseNotesBuilder(github_token=github_token)
    tag_list = noteBuilder._get_all_tags(repo)

    # check tags are valid
    if from_tag not in tag_list:
        raise click.BadParameter(f"from_tag={from_tag}, not found in the {repo} Repository \nValid options: {tag_list}")
    if to_tag not in tag_list:
        raise click.BadParameter(f"to_tag={to_tag}, not found in the {repo} Repository, \nValid options: {tag_list}")

    # Create changelog
    repo_data = noteBuilder.load_data(repo_name=repo, tag_from=from_tag, tag_to=to_tag)
    changelog_data =  noteBuilder.create_changelog(repo_data)
    changelog_path = os.path.abspath(output_path)

    mode = 'r+' if os.path.isfile(changelog_path) else 'w+'
    with open(changelog_path, mode) as cl:
        text = cl.readlines()

        if len(text) > 3:
            # Appending to existing file
            cl.seek(0)
            cl.writelines(text[:3] + changelog_data + text[3:])
            logger.info(f'Appended Changelog data to: "{changelog_path}"')
        else:
            # new file or stub
            cl.seek(0)
            header = [f'{repo} Changelog\n']
            header.append( (len(header[0])-1) * '='+'\n')
            header.append('\n')
            cl.writelines(header + changelog_data)
            logger.info(f'Written Changelog to new file: "{changelog_path}"')

@cli.command()
@click.option('--platform-from-tag', default=None, help='Github tag to track changes from' )
@click.option('--platform-to-tag',   default=None, help='Github tag to track changes to')
@click.option('--ktools-from-tag',   default=None, help='Github tag to track changes from' )
@click.option('--ktools-to-tag',     default=None, help='Github tag to track changes to')
@click.option('--lmf-from-tag',      default=None, help='Github tag to track changes from' )
@click.option('--lmf-to-tag',        default=None, help='Github tag to track changes to')
@click.option('--github-token',      default=None, help='Github OAuth token')
@click.option('--output-path',       type=click.Path(exists=False), default='./RELEASE.md', help='changelog output path')
def build_release_notes(platform_from_tag,
                        platform_to_tag ,
                        ktools_from_tag,
                        ktools_to_tag,
                        lmf_from_tag,
                        lmf_to_tag,
                        github_token,
                        output_path):

    logger = logging.getLogger()
    noteBuilder = ReleaseNotesBuilder(github_token=github_token)
    plat_from   = platform_from_tag if platform_from_tag else noteBuilder._get_tag(repo_name='OasisPlatform', idx=1)
    plat_to     = platform_to_tag if platform_to_tag     else noteBuilder._get_tag(repo_name='OasisPlatform', idx=0)
    lmf_from    = lmf_from_tag if lmf_from_tag           else noteBuilder._get_tag(repo_name='OasisLMF', idx=1)
    lmf_to      = lmf_to_tag if lmf_to_tag               else noteBuilder._get_tag(repo_name='OasisLMF', idx=0)
    ktools_from = ktools_from_tag if ktools_from_tag     else noteBuilder._get_tag(repo_name='ktools', idx=1)
    ktools_to   = ktools_to_tag if ktools_to_tag         else noteBuilder._get_tag(repo_name='ktools', idx=0)

    plat_data = noteBuilder.load_data(repo_name='OasisPlatform', tag_from=plat_from, tag_to=plat_to)
    lmf_data = noteBuilder.load_data(repo_name='OasisLMF',       tag_from=lmf_from, tag_to=lmf_to)
    ktools_data = noteBuilder.load_data(repo_name='ktools',      tag_from=ktools_from, tag_to=ktools_to)

    release_notes_data = noteBuilder.create_release_notes(
        platform_data=plat_data,
        oasislmf_data=lmf_data,
        ktools_data=ktools_data)

    release_notes_path = os.path.abspath(output_path)
    with open(release_notes_path, 'w+') as rn:
        header = [f'Oasis Release Notes v{plat_to} \n']
        header.append( (len(header[0])-1) * '='+'\n')
        header.append('\n')
        rn.writelines(header + release_notes_data)
        logger.info(f'Written Release notes to new file: "{release_notes_path}"')

if __name__ == '__main__':
    cli()
