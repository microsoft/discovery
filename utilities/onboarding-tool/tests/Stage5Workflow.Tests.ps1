$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
$stage5Path = Join-Path $PSScriptRoot '..\scripts\stage5-scenario-enablement\stage5_enable.ps1'
Import-Module $modulePath -Force

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $stage5Path),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
foreach ($name in @(
        'Invoke-Stage5CreateAgent',
        'Invoke-Stage5SendPromptPoll',
        'Invoke-Stage5AssertResponse'
    )) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage5Path." }
    Invoke-Expression $functionAst.Extent.Text
}

function New-Stage5ConfigFile {
    param([string]$Path)
    [pscustomobject]@{
        schemaVersion      = '1.0'
        subscriptionId     = '00000000-0000-0000-0000-000000000000'
        controlPlaneRegion = 'eastus'
        workloadRegion     = 'eastus'
        resourceGroup      = 'platform-rg'
        network            = [pscustomobject]@{
            model     = 'byo'
            vnetCidr  = '10.0.0.0/23'
            subnets   = @()
        }
        sizingTier         = 'Small'
        names              = [pscustomobject]@{
            workspace = 'workspace'
            project   = 'project'
            qnaAgent  = 'scientist-agent'
            chatModel = 'gpt-5-4'
        }
        deployingIdentity  = [pscustomobject]@{ objectId = 'user-id'; type = 'user' }
        rbac               = [pscustomobject]@{ humanAccessMode = 'permanent-role-assignments' }
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding utf8
}

function New-WebResponse {
    param([int]$StatusCode, [object]$Body)
    [pscustomobject]@{
        StatusCode = $StatusCode
        Headers    = @{}
        Content    = if ($null -ne $Body) { $Body | ConvertTo-Json -Depth 20 -Compress } else { '' }
    }
}

Describe 'Stage 5 agent creation request' {
    BeforeEach {
        $global:Stage5Requests = [System.Collections.Generic.List[object]]::new()
        $global:Stage5CreateResponse = New-WebResponse -StatusCode 200 -Body @{ name = 'scientist-agent' }
        Mock Invoke-Az { 'unit-token' }
        Mock Invoke-WebRequest {
            param($Method, $Uri, $Headers, $Body)
            $global:Stage5Requests.Add([pscustomobject]@{ Method = $Method; Uri = $Uri; Headers = $Headers; Body = $Body })
            $global:Stage5CreateResponse
        }
    }

    AfterEach {
        Remove-Variable Stage5Requests, Stage5CreateResponse -Scope Global -ErrorAction SilentlyContinue
    }

    It 'uses bearer authentication and creates an agent with no tools' {
        $configPath = Join-Path $TestDrive 'config.json'
        New-Stage5ConfigFile -Path $configPath

        $result = @(Invoke-Stage5CreateAgent -ConfigPath $configPath -PassThru)
        $body = $global:Stage5Requests[0].Body | ConvertFrom-Json

        $result[0].status | Should Be 'Pass'
        $global:Stage5Requests[0].Headers.Authorization | Should Be 'Bearer unit-token'
        @($body.tools).Count | Should Be 0
        $body.foundryDetails.definition.model | Should Be 'gpt-5-4'
        $global:Stage5Requests[0].Uri | Should Match 'api-version=2026-06-01'
    }
}

Describe 'Stage 5 response polling' {
    BeforeEach {
        $global:Stage5Requests = [System.Collections.Generic.List[object]]::new()
        $global:Stage5WebResponses = [System.Collections.Generic.Queue[object]]::new()
        Mock Invoke-Az { 'unit-token' }
        Mock Start-Sleep {}
        Mock Invoke-WebRequest {
            param($Method, $Uri, $Headers, $Body)
            $global:Stage5Requests.Add([pscustomobject]@{ Method = $Method; Uri = $Uri; Headers = $Headers; Body = $Body })
            if (-not $global:Stage5WebResponses.Count) { throw 'No queued web response.' }
            $global:Stage5WebResponses.Dequeue()
        }
    }

    AfterEach {
        Remove-Variable Stage5Requests, Stage5WebResponses -Scope Global -ErrorAction SilentlyContinue
    }

    It 'sends array content without api-version and completes polling' {
        $configPath = Join-Path $TestDrive 'config.json'
        $responsePath = Join-Path $TestDrive 'response.json'
        New-Stage5ConfigFile -Path $configPath
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 202 -Body @{ id = 'response-id' }))
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 200 -Body @{
                    id = 'response-id'
                    status = 'completed'
                    output = @()
                }))

        $result = @(Invoke-Stage5SendPromptPoll -ConfigPath $configPath -ConversationId 'conversation-id' -PollSeconds 0 -TimeoutSeconds 5 -ResponsePath $responsePath -PassThru)
        $requestBody = $global:Stage5Requests[0].Body | ConvertFrom-Json

        @($result | Where-Object status -eq 'Fail').Count | Should Be 0
        @($requestBody.input[0].content).Count | Should Be 1
        $requestBody.input[0].content[0].type | Should Be 'input_text'
        $global:Stage5Requests[0].Uri | Should Not Match 'api-version'
        $global:Stage5Requests[1].Uri | Should Not Match 'api-version'
        $global:Stage5Requests[0].Headers.Authorization | Should Be 'Bearer unit-token'
        Test-Path -LiteralPath $responsePath | Should Be $true
    }

    It 'fails a successful HTTP response that omits the response id' {
        $configPath = Join-Path $TestDrive 'config.json'
        New-Stage5ConfigFile -Path $configPath
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 200 -Body @{ status = 'accepted' }))

        $result = @(Invoke-Stage5SendPromptPoll -ConfigPath $configPath -ConversationId 'conversation-id' -PassThru)

        $result[0].status | Should Be 'Fail'
        $global:Stage5Requests.Count | Should Be 1
    }

    It 'fails immediately on a terminal failed response' {
        $configPath = Join-Path $TestDrive 'config.json'
        New-Stage5ConfigFile -Path $configPath
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 202 -Body @{ id = 'response-id' }))
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 200 -Body @{ id = 'response-id'; status = 'failed' }))

        $result = @(Invoke-Stage5SendPromptPoll -ConfigPath $configPath -ConversationId 'conversation-id' -PollSeconds 0 -TimeoutSeconds 5 -PassThru)

        @($result | Where-Object { $_.id -eq 'fr5-5-response-completed' })[0].status | Should Be 'Fail'
        $global:Stage5Requests.Count | Should Be 2
    }

    It 'fails without polling when the timeout is already exhausted' {
        $configPath = Join-Path $TestDrive 'config.json'
        New-Stage5ConfigFile -Path $configPath
        $global:Stage5WebResponses.Enqueue((New-WebResponse -StatusCode 202 -Body @{ id = 'response-id' }))

        $result = @(Invoke-Stage5SendPromptPoll -ConfigPath $configPath -ConversationId 'conversation-id' -PollSeconds 0 -TimeoutSeconds 0 -PassThru)

        @($result | Where-Object { $_.id -eq 'fr5-5-response-completed' })[0].status | Should Be 'Fail'
        $global:Stage5Requests.Count | Should Be 1
    }
}

Describe 'Stage 5 response assertions' {
    BeforeEach {
        $script:Stage5ConfigPath = Join-Path $TestDrive 'config.json'
        New-Stage5ConfigFile -Path $script:Stage5ConfigPath
    }

    It 'passes a completed response containing assistant text' {
        $response = [pscustomobject]@{
            status = 'completed'
            output = @([pscustomobject]@{
                    type = 'message'
                    content = @([pscustomobject]@{ type = 'output_text'; text = 'A scientific answer.' })
                })
        }

        $result = @($response | Invoke-Stage5AssertResponse -ConfigPath $script:Stage5ConfigPath -PassThru)

        $result[0].status | Should Be 'Pass'
        $result[0].data.answer | Should Be 'A scientific answer.'
    }

    It 'fails a completed response with no assistant text' {
        $response = [pscustomobject]@{ status = 'completed'; output = @() }

        $result = @($response | Invoke-Stage5AssertResponse -ConfigPath $script:Stage5ConfigPath -PassThru)

        $result[0].status | Should Be 'Fail'
        $result[0].data.hasText | Should Be $false
    }

    It 'fails a non-completed response even when text is present' {
        $response = [pscustomobject]@{
            status = 'failed'
            output = @([pscustomobject]@{
                    type = 'message'
                    content = @([pscustomobject]@{ text = 'partial answer' })
                })
        }

        $result = @($response | Invoke-Stage5AssertResponse -ConfigPath $script:Stage5ConfigPath -PassThru)

        $result[0].status | Should Be 'Fail'
        $result[0].data.completed | Should Be $false
    }

    It 'does not reuse a response object from a previous invocation' {
        $response = [pscustomobject]@{
            status = 'completed'
            output = @([pscustomobject]@{
                    type = 'message'
                    content = @([pscustomobject]@{ text = 'answer' })
                })
        }
        $null = @($response | Invoke-Stage5AssertResponse -ConfigPath $script:Stage5ConfigPath -PassThru)

        $result = @(Invoke-Stage5AssertResponse -ConfigPath $script:Stage5ConfigPath -PassThru)

        $result[0].id | Should Be 'fr5-6-response-input'
        $result[0].status | Should Be 'Fail'
    }
}
