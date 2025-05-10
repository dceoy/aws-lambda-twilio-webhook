variable "REGISTRY" {
  default = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
}

variable "TAG" {
  default = "latest"
}

variable "PYTHON_VERSION" {
  default = "3.13"
}

variable "USER_UID" {
  default = 1001
}

variable "USER_GID" {
  default = 1001
}

variable "USER_NAME" {
  default = "lambda"
}

group "default" {
  targets = ["twilio-webhook-handler"]
}

target "twilio-webhook-handler" {
  tags       = ["${REGISTRY}/twilio-webhook-handler:${TAG}"]
  context    = "."
  dockerfile = "src/Dockerfile"
  target     = "app"
  platforms  = ["linux/arm64"]
  args = {
    PYTHON_VERSION = PYTHON_VERSION
    USER_UID       = USER_UID
    USER_GID       = USER_GID
    USER_NAME      = USER_NAME
  }
  cache_from = ["type=gha"]
  cache_to   = ["type=gha,mode=max"]
  pull       = true
  push       = false
  load       = true
  provenance = false
}
