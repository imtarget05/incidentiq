package incidentiq.kubernetes.admission

deny[msg] {
    input.review.kind.kind == "Deployment"
    image := input.review.object.spec.template.spec.containers[_].image
    endswith(image, ":latest")
    msg := sprintf("Image '%v' uses 'latest' tag", [image])
}

deny[msg] {
    input.review.kind.kind == "Deployment"
    not input.review.object.spec.template.spec.securityContext.runAsNonRoot == true
    msg := "Deployment must set spec.securityContext.runAsNonRoot=true"
}

deny[msg] {
    input.review.kind.kind == "Deployment"
    container := input.review.object.spec.template.spec.containers[_]
    not container.resources.limits
    msg := sprintf("Container '%v' must define resource limits", [container.name])
}
