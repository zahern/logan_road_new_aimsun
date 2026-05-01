	subroutine kspcost_main(dy_muc)
c --
c -- This subroutine is the main subroutine for the shortest path calculations. 
c --
c -- This subroutine is called from main and loop
c -- This subroutine call the following subroutines:
c -- 1. ksp_init
c -- 2. ksp_calculate
c -- 3. ksp_integrate
c -- 4. ksp_priorities
c --
c -- INPUT: 
c --  no specific input
c -- OUTPUT:
c --  no specific output
c --
c       include 'common.inc'
      use muc_mod
	use vector_mod					! Alex: unnecessary
c -- 
c --  dy_muc is the indicator to let ksp_main know if it is called by dynasmart or muc.  
c --  If dy_muc = 0, called from dynasmart, them do not use TD feature
c --  If dy_muc = 1, called from muc, use TD feature
	integer dy_muc
	real tiempo
c --
c --	Travel time
c --  	Iti_nu has changed to be a variable = nint(stagelength)
c --	print *,'AlexUE021'
      kpaths=kay
	if(dy_muc.eq.0)then  !dynasmart
	  do ilink=1,noofarcs
         do itt=1,Iti_nu
          TTime(ilink,itt)=TTimeOfBackLink(ilink)
         enddo
	  enddo
      else
	  do ilink=1,noofarcs
         do itt=1,Iti_nu
          TTime(ForToBackLink(ilink),itt)=TravelTime(ilink,itt)
         enddo
        enddo
      endif
c --  Penalty
      if(dy_muc.eq.0)then
        do ilink=1,noofarcs
         do itt=1,Iti_nu
          do movee=1,nu_mv
c	if(ilink.gt.580.or.itt.gt.1.or.movee.gt.12) stop
	    TTPenalty(ilink,itt,movee)=penalty(ilink,movee)
          enddo
         enddo
        enddo
    	else
        do ilink=1,noofarcs
         do itt=1,Iti_nu
          do movee=1,nu_mv
c	if(ilink.gt.580.or.itt.gt.1.or.movee.gt.12) stop
          TTPenalty(ilink,itt,movee)=TravelPenalty(ilink,itt,movee)
          enddo
         enddo
        enddo
	endif
c --
c --	print *,'AlexUE022'
c	if (tiempo.gt.2.7)
c     +	print *, 'Alex721',VhcAtt_Value(42,12,1)
c --
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
! Initialize TTPenalty from any connector to outbound links as infinity
        do ilink=1,noofarcs
	if(link_iden(ilink).eq.100)then ! connector 
c --
	icentroid=iunod(ilink) ! Centroid node ID for connector
c --	
	do iaa=1,llink(ilink,nu_mv+1) ! for each outbound link of connector
        ioutboundlink=llink(ilink,iaa)
	iupstreamnode=iunod(ioutboundlink) ! Upstream node ID for outbound link
	Movements=BackPointr(iupstreamnode+1)-BackPointr(iupstreamnode) ! number of incoming movements wrt node iupstreamnode
	imovement=-1
       do m=1,Movements
	 NTransient=BackPointr(iupstreamnode)+m-1
         Nodee=UNodeOfBackLink(NTransient) ! upstream node of link NTransient (in backward star)
	  if(icentroid.eq.Nodee)then
	  imovement=m 
	  endif
	enddo
c --
c	if(iteration.gt.0) print *,'AlexUE022'
	if(imovement.eq.-1)then
	write(*,*) "cannot find corresponding movement from a connector
     + to current outbound link"
	stop
	endif
c --
      ioutboundlinkback=ForToBackLink(ioutboundlink)
c	if(ioutboundlinkback.gt.580.or.imovement.gt.12) stop
      TTPenalty(ioutboundlinkback,:,imovement)=infinity
c --
	enddo
	endif
	enddo
c --
c --	print *,'AlexUE023'
c	if (tiempo.gt.2.7)
c     +	print *, 'Alex722',VhcAtt_Value(42,12,1)
! Put entry queue time as TTPenalty from a connector to outbound generation links
c --
      do iz=1,nzones
        do il=1,NoofGenLinksPerZone(iz)
	igenelink=LinkNoInZone(iz,il)
	icentroid=origin(iz) ! Centroid node ID for origin zone iz
	iupstreamnode=iunod(igenelink) ! Upstream node ID for generation link igenelink
	Movements=BackPointr(iupstreamnode+1)-BackPointr(iupstreamnode) ! number of incoming movements wrt node iupstreamnode
	imovement=-1
c	if (tiempo.gt.2.7)
c     +	print *, 'Alex7221',VhcAtt_Value(42,12,1)
        do m=1,Movements
	  NTransient=BackPointr(iupstreamnode)+m-1
          Nodee=UNodeOfBackLink(NTransient) ! upstream node of link NTransient (in backward star)
	  if(icentroid.eq.Nodee) imovement=m
	enddo
c	if (tiempo.gt.2.7)
c	if(iteration.gt.0) print *, 'Alex7222'      
	if(imovement.eq.-1)then
	write(*,*) "cannot find corresponding movement from a connector
     +  to current generation link"
	stop
	endif
c --
      	  igenelinkback=ForToBackLink(igenelink)
c --
	  if(ALLOCATED(PenaltyEntry))then
c	if(igenelinkback.gt.580.or.imovement.gt.12) stop
      TTPenalty(igenelinkback,:,imovement)=PenaltyEntry(igenelink,:)
	  else
c	if(igenelinkback.gt.580.or.imovement.gt.12) stop
          TTPenalty(igenelinkback,:,imovement)=0
	  endif
	enddo
	enddo
	endif
c --
c --	print *,'AlexUE024'
c	if (tiempo.gt.2.7)
c     +	print *, 'Alex723',VhcAtt_Value(42,12,1)
c --  Construct final cost
c --  
       do ilink=1,noofarcs
        do itt=1,Iti_nu
         do movee=1,nu_mv
	    if(dy_muc.eq.2)then ! SO case
c	if(ilink.gt.580.or.itt.gt.1.or.movee.gt.12) stop
           TTmarginal(itt,ilink,movee)=TTime(ilink,itt)+
     *     TTPenalty(ilink,itt,movee)+PenaltyMG(itt,ilink,movee)
          else ! UE or static case
c	if(ilink.gt.580.or.itt.gt.1.or.movee.gt.12) stop
           TTmarginal(itt,ilink,movee)=TTime(ilink,itt)+
     *     TTPenalty(ilink,itt,movee)
	  endif
          enddo
        enddo
       enddo
c --
c --  PenaltyEntryMG is the marginal link entry queue
c         PenaltyEntryMG(:,:)=PenaltyEntry(:,:)
c --
c	print *,'AlexUE025'

         do ides=1,noof_master_destinations
          do ltype=1,no_link_type
           do ioccup=1,no_occupancy_level
!             destin=destination(ides)
c --
	if(dy_muc.eq.0)then  !dynasmart
	  destin=destination(ides)
        else
	  destin=destination(real_SuperzoneIndex)
        endif
! End of change
	       if(destin.ne.0)then
c	print *,'AlexUE0251'
               call kspcost_init
c	print *,'AlexUE0252'
               call kspcost_calculate
c	print *,'AlexUE0253'
               call kspcost_integrate
c	print *,'AlexUE0254'
			 if(dy_muc.eq.0)then
c	print *,'AlexUE0255'
                 if(time_now.le.1) call network_check(ides)
c	print *,'AlexUE0256'
                 call kspcost_priorities
c	print *,'AlexUE0257'
			 endif
	       endif
      	 enddo
         enddo
         enddo
c --
c	print *,'AlexUE026'
c --
!	   if(time_now.le.1) call CheckGenLinkOnConnectivity()
c --
        return
        end
